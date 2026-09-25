"""Install USB chat host deps. Never creates a venv on the stick."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MIN_VERSION = (3, 11)
PACKAGE = "llama-cpp-python>=0.3.35"

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def on_usb_stick(here: Path | None = None) -> bool:
    here = (here or HERE).resolve()
    parent = here.parent
    return parent.parent == parent or any(parent.glob("*.gguf"))


def repo_venv_python(here: Path | None = None) -> Path | None:
    here = (here or HERE).resolve()
    if on_usb_stick(here):
        return None
    for rel in (Path(".venv") / "Scripts" / "python.exe", Path(".venv") / "bin" / "python"):
        cand = here.parent / rel
        if cand.is_file():
            return cand
    return None


def have_llama_cpp() -> bool:
    try:
        import llama_cpp  # noqa: F401

        return True
    except ImportError:
        return False


def have_llama_cli(here: Path | None = None) -> bool:
    import usbchat

    return usbchat.find_llama_cli(here or HERE) is not None


def _is_venv_python(executable: Path) -> bool:
    parts = {p.lower() for p in executable.resolve().parts}
    return ".venv" in parts or "venv" in parts


def install_args(executable: Path) -> list[str]:
    cmd = [str(executable), "-m", "pip", "install"]
    if not _is_venv_python(executable):
        cmd.append("--user")
    cmd.append(PACKAGE)
    return cmd


def _print_requirements() -> None:
    print("USB chat host setup")
    print("Needs on this PC:")
    print("  - Python 3.11 or newer (from python.org or apt, on PATH)")
    print("  - llama-cpp-python  OR  llama-cli in chat/bin/")
    print("Will not create a .venv on the USB stick.")
    print()


def main(argv: list[str] | None = None) -> int:
    del argv
    _print_requirements()
    if sys.version_info < MIN_VERSION:
        print(
            f"This Python is {sys.version.split()[0]}. Install 3.11+ and run setup again.",
            file=sys.stderr,
        )
        return 1

    if have_llama_cli():
        print(f"OK: llama-cli is available. Python {sys.version.split()[0]}")
        return 0
    if have_llama_cpp():
        print(f"OK: llama-cpp-python is already importable. Python {sys.version.split()[0]}")
        return 0

    current = Path(sys.executable)
    print(f"Installing {PACKAGE} for {current}")
    try:
        subprocess.check_call(install_args(current))
    except subprocess.CalledProcessError:
        print(
            "pip failed. Install llama-cpp-python by hand, or put llama-cli in chat/bin/.",
            file=sys.stderr,
        )
        return 1

    extra = repo_venv_python()
    if extra is not None and extra.resolve() != current.resolve():
        print(f"Also installing into the repo venv (chat.bat prefers it): {extra}")
        try:
            subprocess.check_call(install_args(extra))
        except subprocess.CalledProcessError:
            print("Repo venv install failed; host install already finished.", file=sys.stderr)

    print("Done. Run chat.bat / chat.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
