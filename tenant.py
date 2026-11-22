"""LAN device tenancy. Agents never import this file.

A household client is keyed by a hashed Wi-Fi MAC when the TCP peer is on
the same L2 (ARP/NDP). That id stays stable across DHCP renewals and
reconnects to this SSID. Loopback, VPN, and AP isolation fall back to a
cookie / claimed UUID. IP is recorded for analytics only and is never used
to look up a session.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

COOKIE_NAME = "mayavi_device"
INDEX_NAME = "index.json"
MAC_HASH_LEN = 12

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_DEV_RE = re.compile(r"^dev_[0-9a-f]{12}$", re.I)
_MAC_PAIR = re.compile(r"([0-9a-f]{2})(?:[:\-])?", re.I)
_WIN_ARP = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+((?:[0-9a-f]{2}[-:]){5}[0-9a-f]{2})\s+",
    re.I,
)
_UNIX_ARP = re.compile(
    r"\((\d{1,3}(?:\.\d{1,3}){3})\)\s+at\s+((?:[0-9a-f]{2}:){5}[0-9a-f]{2})",
    re.I,
)
_PROC_ARP = re.compile(
    r"^(\d{1,3}(?:\.\d{1,3}){3})\s+\S+\s+(0x[0-9a-f]+)\s+((?:[0-9a-f]{2}:){5}[0-9a-f]{2})",
    re.I,
)
_V6_NEIGH = re.compile(
    r"([0-9a-f:]+)\s+.*?((?:[0-9a-f]{2}[:\-]){5}[0-9a-f]{2})",
    re.I,
)
_LOCK = threading.Lock()
_ARP_CACHE: dict[str, str] = {}
_ARP_CACHE_AT = 0.0
_ARP_TTL = 5.0


@dataclass(frozen=True)
class Tenant:
    id: str
    source: str
    set_cookie: bool = True


def parse_device_id(raw: Any) -> str | None:
    text = str(raw or "").strip().lower()
    if _UUID_RE.fullmatch(text) or _DEV_RE.fullmatch(text):
        return text
    return None


def device_dir(device_id: str) -> Path | None:
    did = parse_device_id(device_id)
    if not did:
        return None
    root = config.UI_SESSION_DIR.resolve()
    target = (root / did).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


def cookie_header(device_id: str) -> str:
    did = parse_device_id(device_id)
    if not did:
        raise ValueError("bad_device")
    return f"{COOKIE_NAME}={did}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000"


def parse_cookie(header: str | None) -> str | None:
    raw = str(header or "")
    for part in raw.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        if name.strip() == COOKIE_NAME:
            return parse_device_id(value.strip())
    return None


def mac_hash(mac: str) -> str | None:
    packed = _mac_bytes(mac)
    if packed is None:
        return None
    return hashlib.sha256(packed).hexdigest()[:MAC_HASH_LEN]


def tenant_id_for_mac(mac: str) -> str | None:
    digest = mac_hash(mac)
    if not digest:
        return None
    return f"dev_{digest}"


def lookup_mac(ip: str) -> str | None:
    """Hardware address for a LAN peer. Empty for loopback or unknown."""
    try:
        addr = ipaddress.ip_address(str(ip or "").strip())
    except ValueError:
        return None
    if addr.is_loopback or addr.is_unspecified or addr.is_multicast:
        return None
    table = _neighbor_table()
    return table.get(_ip_key(addr))


def resolve(
    *,
    ip: str = "",
    cookie: str | None = None,
    claimed: str | None = None,
    mint: bool = False,
) -> Tenant | None:
    """Pick a stable tenant. MAC wins when this host has seen that peer before.

    mint=True (whoami) may create a new id. Other routes only return a known
    cookie, claimed folder, or MAC mapping.
    """
    claimed_id = parse_device_id(claimed)
    cookie_id = parse_device_id(cookie)
    mac = lookup_mac(ip)
    mac_key = mac_hash(mac) if mac else None
    with _LOCK:
        index = _load_index()
        if mac_key:
            mapped = (index.get("mac") or {}).get(mac_key)
            mapped_id = parse_device_id(mapped)
            if mapped_id:
                _touch(index, mapped_id, mac_key=mac_key, alias=claimed_id or cookie_id, ip=ip)
                _save_index(index)
                return Tenant(id=mapped_id, source="mac")
        existing = _existing_id(index, claimed_id) or _existing_id(index, cookie_id)
        if existing:
            if mac_key:
                _touch(index, existing, mac_key=mac_key, alias=claimed_id or cookie_id, ip=ip)
            else:
                _touch(index, existing, alias=claimed_id or cookie_id, ip=ip)
            _save_index(index)
            source = "claimed" if claimed_id and _canonical(index, claimed_id) == existing else "cookie"
            return Tenant(id=existing, source=source)
        if claimed_id and device_dir(claimed_id) is not None and (device_dir(claimed_id) / "session.jsonl").is_file():
            _touch(index, claimed_id, mac_key=mac_key, ip=ip)
            _save_index(index)
            return Tenant(id=claimed_id, source="claimed")
        if cookie_id and device_dir(cookie_id) is not None and (device_dir(cookie_id) / "session.jsonl").is_file():
            _touch(index, cookie_id, mac_key=mac_key, ip=ip)
            _save_index(index)
            return Tenant(id=cookie_id, source="cookie")
        if not mint:
            if claimed_id:
                _touch(index, claimed_id, mac_key=mac_key, ip=ip)
                _save_index(index)
                return Tenant(id=claimed_id, source="claimed")
            if cookie_id:
                _touch(index, cookie_id, mac_key=mac_key, ip=ip)
                _save_index(index)
                return Tenant(id=cookie_id, source="cookie")
            return None
        if mac_key:
            minted = f"dev_{mac_key}"
            _touch(index, minted, mac_key=mac_key, alias=claimed_id or cookie_id, ip=ip)
            _save_index(index)
            folder = device_dir(minted)
            if folder is not None:
                folder.mkdir(parents=True, exist_ok=True)
            return Tenant(id=minted, source="mac")
        minted = claimed_id or cookie_id or str(uuid.uuid4())
        _touch(index, minted, alias=claimed_id or cookie_id, ip=ip)
        _save_index(index)
        folder = device_dir(minted)
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=True)
        return Tenant(id=minted, source="new" if not (claimed_id or cookie_id) else ("claimed" if claimed_id else "cookie"))


def record_ip(device_id: str, ip: str) -> None:
    """Sidecar only. Does not change which tenant an IP maps to."""
    did = parse_device_id(device_id)
    if not did:
        return
    with _LOCK:
        index = _load_index()
        _touch(index, did, ip=ip)
        _save_index(index)


def parse_arp_output(text: str) -> dict[str, str]:
    """Parse arp -a / /proc/net/arp / ip neigh text into ip → mac."""
    table: dict[str, str] = {}
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("interface:") or line.lower().startswith("internet address"):
            continue
        ip = ""
        mac = ""
        proc = _PROC_ARP.match(line)
        if proc:
            flags = int(proc.group(2), 16)
            if flags & 0x2:
                ip, mac = proc.group(1), proc.group(3)
        if not ip:
            win = _WIN_ARP.match(line)
            if win:
                ip, mac = win.group(1), win.group(2)
        if not ip:
            unix = _UNIX_ARP.search(line)
            if unix:
                ip, mac = unix.group(1), unix.group(2)
        if not ip:
            v6 = _V6_NEIGH.search(line)
            if v6 and ":" in v6.group(1):
                ip, mac = v6.group(1), v6.group(2)
        packed = _mac_bytes(mac)
        if not ip or packed is None:
            continue
        try:
            addr = ipaddress.ip_address(ip.split("%", 1)[0])
        except ValueError:
            continue
        if addr.is_loopback or addr.is_unspecified or addr.is_multicast:
            continue
        table[_ip_key(addr)] = packed.hex()
    return table


def _neighbor_table() -> dict[str, str]:
    import time

    global _ARP_CACHE, _ARP_CACHE_AT
    now = time.monotonic()
    if _ARP_CACHE and now - _ARP_CACHE_AT < _ARP_TTL:
        return _ARP_CACHE
    table: dict[str, str] = {}
    proc = Path("/proc/net/arp")
    if proc.is_file():
        try:
            table.update(parse_arp_output(proc.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            pass
    for argv in (
        ["arp", "-a"],
        ["ip", "-6", "neigh", "show"],
        ["netsh", "interface", "ipv6", "show", "neighbors"],
    ):
        try:
            out = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        blob = (out.stdout or "") + "\n" + (out.stderr or "")
        table.update(parse_arp_output(blob))
    _ARP_CACHE = table
    _ARP_CACHE_AT = now
    return table


def _mac_bytes(mac: str) -> bytes | None:
    hexes = _MAC_PAIR.findall(str(mac or "").replace(".", ":"))
    if len(hexes) != 6:
        compact = re.sub(r"[^0-9a-f]", "", str(mac or ""), flags=re.I)
        if len(compact) != 12:
            return None
        hexes = [compact[i : i + 2] for i in range(0, 12, 2)]
    packed = bytes(int(part, 16) for part in hexes)
    if packed in {b"\x00" * 6, b"\xff" * 6}:
        return None
    if packed[0] & 1:
        return None
    return packed


def _ip_key(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        return str(addr.ipv4_mapped)
    return str(addr)


def _index_path() -> Path:
    return config.UI_SESSION_DIR / INDEX_NAME


def _empty_index() -> dict[str, Any]:
    return {"mac": {}, "alias": {}, "tenants": {}}


def _load_index() -> dict[str, Any]:
    path = _index_path()
    if not path.is_file():
        return _empty_index()
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return _empty_index()
    if not isinstance(blob, dict):
        return _empty_index()
    out = _empty_index()
    for key in out:
        raw = blob.get(key)
        if isinstance(raw, dict):
            out[key] = {str(k): v for k, v in raw.items()}
    return out


def _save_index(index: dict[str, Any]) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _canonical(index: dict[str, Any], device_id: str | None) -> str | None:
    did = parse_device_id(device_id)
    if not did:
        return None
    alias = parse_device_id((index.get("alias") or {}).get(did))
    return alias or did


def _existing_id(index: dict[str, Any], device_id: str | None) -> str | None:
    did = _canonical(index, device_id)
    if not did:
        return None
    tenants = index.get("tenants") or {}
    if did in tenants:
        return did
    folder = device_dir(did)
    if folder is not None and folder.is_dir():
        return did
    return None


def _touch(
    index: dict[str, Any],
    device_id: str,
    *,
    mac_key: str | None = None,
    alias: str | None = None,
    ip: str = "",
) -> None:
    did = parse_device_id(device_id)
    if not did:
        return
    tenants: dict[str, Any] = index.setdefault("tenants", {})
    row = tenants.get(did)
    if not isinstance(row, dict):
        row = {"id": did, "aliases": [], "seen_ips": [], "updated": ""}
    aliases = [str(item).lower() for item in (row.get("aliases") or []) if parse_device_id(item)]
    if alias:
        other = parse_device_id(alias)
        if other and other != did and other not in aliases:
            aliases.append(other)
        if other and other != did:
            index.setdefault("alias", {})[other] = did
    if mac_key:
        index.setdefault("mac", {})[mac_key] = did
    seen = [str(item) for item in (row.get("seen_ips") or []) if str(item).strip()]
    ip_text = str(ip or "").strip()[:80]
    if ip_text and ip_text not in seen:
        seen.append(ip_text)
    row["id"] = did
    row["aliases"] = aliases[-12:]
    row["seen_ips"] = seen[-8:]
    row["updated"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    tenants[did] = row
    index.setdefault("alias", {})[did] = did
