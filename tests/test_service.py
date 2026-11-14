"""Checks for automolcraft.service: the LaunchAgent plist and its parsing. Touches nothing on the system.

    python tests/test_service.py        (or: pytest tests/test_service.py)

It never calls launchctl and never writes to ~/Library: install/uninstall/restart are exercised by
hand with `automolcraft service install --print` / `install` / `status` / `uninstall`.
"""
from __future__ import annotations

import plistlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automolcraft import service  # noqa: E402


def _render(host: str = "127.0.0.1", port: int = 9000) -> dict:
    raw = service.render_plist(host, port, Path("/repo"), Path("/logs/serve.log"), Path("/env/bin"))
    return plistlib.loads(raw)


def test_plist_runs_serve_without_opening_a_browser() -> None:
    data = _render()
    args = data["ProgramArguments"]
    assert args[args.index("serve"):] == ["serve", "--no-browser", "--host", "127.0.0.1", "--port", "9000"]
    assert data["Label"] == service.LABEL


def test_plist_starts_at_login_and_restarts_on_crash() -> None:
    data = _render()
    assert data["RunAtLoad"] is True and data["KeepAlive"] is True
    assert data["WorkingDirectory"] == "/repo"
    assert data["StandardOutPath"] == data["StandardErrorPath"] == "/logs/serve.log"


def test_plist_puts_the_envs_bin_first_on_path() -> None:
    # The backend launches MolCraftDiff / xtb / obabel by name; they live next to this Python.
    path = _render()["EnvironmentVariables"]["PATH"].split(":")
    assert path[0] == "/env/bin" and "/usr/bin" in path


def test_installed_endpoint_round_trips_through_the_plist() -> None:
    original = service.plist_path
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "agent.plist"
        target.write_bytes(service.render_plist("0.0.0.0", 9123, Path("/repo"), Path("/l.log"), Path("/env/bin")))
        service.plist_path = lambda: target  # type: ignore[assignment]
        try:
            assert service._installed_endpoint() == ("0.0.0.0", 9123)
            target.unlink()
            assert service._installed_endpoint() is None
            target.write_text("not a plist")
            assert service._installed_endpoint() is None
        finally:
            service.plist_path = original  # type: ignore[assignment]


def test_only_loopback_counts_as_local() -> None:
    assert service._is_loopback("127.0.0.1") and service._is_loopback("localhost")
    assert not service._is_loopback("0.0.0.0") and not service._is_loopback("192.168.1.5")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    print(f"OK: {len(tests)} service checks")
