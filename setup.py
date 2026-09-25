"""Host setup for USB chat. Never changes system Python or writes a venv on the stick."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

MIN_VERSION = (3, 11)
MIN_LABEL = "3.11"
PACKAGE = "llama-cpp-python>=0.3.35"
CPU_WHEEL_INDEX = "https://abetlen.github.io/llama-cpp-python/whl/cpu"

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def min_label() -> str:
    return MIN_LABEL


def host_venv_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "usb-chat" / "venv"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "usb-chat" / "venv"
    return Path.home() / ".local" / "share" / "usb-chat" / "venv"


def venv_python(root: Path | None = None) -> Path:
    root = root or host_venv_root()
    if sys.platform == "win32":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def show_alert(message: str, title: str = "USB chat setup") -> None:
    print(message, file=sys.stderr)
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x30)
        return
    if shutil.which("zenity"):
        subprocess.run(
            ["zenity", "--error", "--title", title, "--width", "420", "--text", message],
            check=False,
        )
        return
    if shutil.which("kdialog"):
        subprocess.run(["kdialog", "--title", title, "--error", message], check=False)


def incompatible_message(found: str) -> str:
    have = "no Python on PATH" if found in {"", "none"} else f"Python {found}"
    return (
        f"USB chat needs Python {MIN_LABEL} or newer to run.\n\n"
        f"This PC has {have}.\n\n"
        "The existing interpreter will not be replaced or upgraded, "
        "so other projects keep using it.\n\n"
        f"Install Python {MIN_LABEL} or newer alongside, then run setup again."
    )


def python_version(executable: Path) -> tuple[int, int, int] | None:
    try:
        out = subprocess.check_output(
            [
                str(executable),
                "-c",
                "import sys; print('%d.%d.%d' % sys.version_info[:3])",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        parts = out.split(".")
        return int(parts[0]), int(parts[1]), int(parts[2])
    except (OSError, subprocess.CalledProcessError, ValueError, IndexError):
        return None


def version_ok(ver: tuple[int, int, int] | None) -> bool:
    return ver is not None and ver[:2] >= MIN_VERSION


def ensure_host_venv(base_python: Path) -> Path:
    root = host_venv_root()
    py = venv_python(root)
    ver = python_version(py) if py.is_file() else None
    if version_ok(ver):
        print(f"Reusing host venv {root} (Python {ver[0]}.{ver[1]}.{ver[2]})")
        return py
    if py.is_file():
        print(f"Replacing usb-chat venv only (was Python {ver or 'unknown'}); system Python is untouched.")
        shutil.rmtree(root, ignore_errors=True)
    print(f"Creating host venv at {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call([str(base_python), "-m", "venv", str(root)])
    return venv_python(root)


class LlamaCppInstallError(RuntimeError):
    """Raised when llama-cpp-python is missing and pip cannot install it."""


def upgrade_packages(executable: Path) -> None:
    subprocess.check_call(
        [str(executable), "-m", "pip", "install", "-U", "pip"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    # PyPI only has a source tarball. Without this index, pip tries to compile
    # and fails on machines with no Visual Studio / nmake.
    try:
        subprocess.check_call(
            [
                str(executable),
                "-m",
                "pip",
                "install",
                "-U",
                "--prefer-binary",
                "--only-binary=llama-cpp-python",
                "--extra-index-url",
                CPU_WHEEL_INDEX,
                PACKAGE,
            ],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    except subprocess.CalledProcessError as exc:
        raise LlamaCppInstallError from exc


def llama_cpp_missing_message() -> str:
    return (
        "USB chat could not install the llama-cpp-python library.\n\n"
        "That library is required to load GGUF models. It is missing from the "
        "usb-chat environment on this PC.\n\n"
        "Setup tried to download a prebuilt CPU wheel. It did not compile from "
        "source, and it did not change your system Python.\n\n"
        "Check you are online and run setup again, or put llama-cli in chat\\bin\\."
    )


def have_llama_cli() -> bool:
    import usbchat

    return usbchat.find_llama_cli(HERE) is not None


def main(argv: list[str] | None = None) -> int:
    del argv
    print("USB chat host setup")
    print(f"Needs Python {MIN_LABEL}+. Will not change the system interpreter.")
    print("Deps go in a host venv (%LOCALAPPDATA%\\usb-chat\\venv or ~/.local/share/usb-chat/venv).")
    print()

    current = Path(sys.executable)
    if sys.version_info[:2] < MIN_VERSION:
        show_alert(incompatible_message(sys.version.split()[0]))
        return 1

    try:
        vpy = ensure_host_venv(current)
    except subprocess.CalledProcessError:
        show_alert(
            "Could not create the usb-chat host venv. "
            f"Python {MIN_LABEL}+ is present, but python -m venv failed. "
            "System Python was not changed."
        )
        return 1

    if have_llama_cli():
        print("llama-cli is present; still keeping the host venv for the chat window.")
    print(f"Updating packages in {vpy} (not the system Python)")
    try:
        upgrade_packages(vpy)
    except LlamaCppInstallError:
        show_alert(llama_cpp_missing_message())
        return 1
    except subprocess.CalledProcessError:
        show_alert(
            "USB chat could not update pip inside its private host venv. "
            "The llama-cpp-python library was not installed. "
            "System Python was not changed. Run setup again, or put llama-cli in chat\\bin\\."
        )
        return 1

    print("Done. Run chat.bat / chat.sh (it uses the host venv).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
