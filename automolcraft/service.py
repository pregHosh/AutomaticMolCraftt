"""Run the web app as a macOS login service (a launchd LaunchAgent).

    automolcraft service install [--host 127.0.0.1] [--port 8000]   start now and at every login
    automolcraft service install --print                            show the plist, change nothing
    automolcraft service status | restart | logs
    automolcraft service uninstall

A LaunchAgent runs in your own login session, so it sees your files and needs no sudo. launchd
restarts the server if it crashes. Nothing here runs unless you call `service install`.
"""
from __future__ import annotations

import os
import plistlib
import socket
import subprocess
import sys
import time
from pathlib import Path

LABEL = "io.github.preghosh.automolcraft"
SYSTEM_PATH = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "automolcraft" / "serve.log"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _say(msg: str) -> None:
    print(f"[automolcraft] {msg}", flush=True)


def _fail(msg: str) -> None:
    print(f"[automolcraft] error: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def program_arguments(host: str, port: int) -> list[str]:
    """argv launchd runs: this environment's `automolcraft` script, else `python -m`."""
    script = Path(sys.executable).parent / "automolcraft"
    head = [str(script)] if script.is_file() else [sys.executable, "-m", "automolcraft.cli"]
    return [*head, "serve", "--no-browser", "--host", host, "--port", str(port)]


def render_plist(host: str, port: int, workdir: Path, log_file: Path, python_bin_dir: Path) -> bytes:
    """The LaunchAgent definition. Pure: reads nothing from the machine except its arguments."""
    env_path = os.pathsep.join([str(python_bin_dir), *SYSTEM_PATH])
    data = {
        "Label": LABEL,
        "ProgramArguments": program_arguments(host, port),
        "WorkingDirectory": str(workdir),
        # The backend launches MolCraftDiff / xtb / obabel by name; they live next to this Python.
        "EnvironmentVariables": {"PATH": env_path, "PYTHONUNBUFFERED": "1"},
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_file),
        "StandardErrorPath": str(log_file),
    }
    return plistlib.dumps(data, sort_keys=False)


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def _is_loaded() -> bool:
    return _launchctl("print", f"{_domain()}/{LABEL}").returncode == 0


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def _require_macos() -> None:
    if sys.platform != "darwin":
        _fail("`service` uses launchd and is macOS-only. On Linux, run `automolcraft serve --no-browser` "
              "from a systemd user unit.")


def _installed_endpoint() -> tuple[str, int] | None:
    """(host, port) the installed plist serves on, or None when not installed."""
    try:
        args = plistlib.loads(plist_path().read_bytes())["ProgramArguments"]
        return args[args.index("--host") + 1], int(args[args.index("--port") + 1])
    except (OSError, ValueError, KeyError, IndexError, plistlib.InvalidFileException):
        return None


def install(host: str, port: int, print_only: bool, root: Path, ensure_frontend) -> None:
    _require_macos()
    plist = render_plist(host, port, root, log_path(), Path(sys.executable).parent)
    if print_only:
        sys.stdout.write(plist.decode())
        return

    if not _is_loopback(host):
        _say(f"warning: binding to {host} makes the app reachable from other machines on your network. "
             "It can read files on this Mac by path and has no login; use it only on a network you trust.")

    ensure_frontend()  # build now, so the service does not spend its first minute doing it

    if _is_loaded():
        _say("replacing the running service")
        _launchctl("bootout", f"{_domain()}/{LABEL}")
        time.sleep(1)
    if _port_open("127.0.0.1" if host in ("0.0.0.0", "::") else host, port):
        _fail(f"port {port} is already in use by another process; pick one with --port")

    log_path().parent.mkdir(parents=True, exist_ok=True)
    plist_path().parent.mkdir(parents=True, exist_ok=True)
    tmp = plist_path().with_suffix(".plist.tmp")
    tmp.write_bytes(plist)
    tmp.replace(plist_path())

    out = _launchctl("bootstrap", _domain(), str(plist_path()))
    if out.returncode != 0:
        _fail(f"launchctl bootstrap failed: {(out.stderr or out.stdout).strip()}")

    local = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if _port_open(local, port):
            _say(f"running: http://{local}:{port}   (starts at every login)")
            _say(f"log: {log_path()}")
            return
        time.sleep(0.5)
    _fail(f"installed, but nothing is listening on {local}:{port} after 90 s; see {log_path()}")


def uninstall() -> None:
    _require_macos()
    if _is_loaded():
        _launchctl("bootout", f"{_domain()}/{LABEL}")
    if plist_path().exists():
        plist_path().unlink()
        _say(f"removed {plist_path()}")
    else:
        _say("not installed")


def restart() -> None:
    _require_macos()
    if not _is_loaded():
        _fail("the service is not loaded; run `automolcraft service install`")
    out = _launchctl("kickstart", "-k", f"{_domain()}/{LABEL}")
    if out.returncode != 0:
        _fail(f"launchctl kickstart failed: {(out.stderr or out.stdout).strip()}")
    _say("restarted")


def status() -> None:
    _require_macos()
    endpoint = _installed_endpoint()
    if endpoint is None:
        _say("not installed (run `automolcraft service install`)")
        return
    host, port = endpoint
    loaded = _is_loaded()
    local = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    listening = _port_open(local, port)
    print(f"  plist    {plist_path()}")
    print(f"  loaded   {'yes' if loaded else 'no'}")
    print(f"  serving  {'yes -> http://%s:%d' % (local, port) if listening else 'no'}")
    print(f"  log      {log_path()}")
    if not loaded:
        _say("installed but not loaded; `automolcraft service install` loads it again")


def logs(lines: int = 40) -> None:
    path = log_path()
    if not path.exists():
        _say(f"no log yet at {path}")
        return
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - 64 * 1024))
        tail = fh.read().decode("utf-8", errors="replace").splitlines()[-lines:]
    print("\n".join(tail))
