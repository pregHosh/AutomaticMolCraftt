"""Check external command plugins end to end, using plugins/nhc_buried_volume.

    python test_plugins.py

Covers discovery, argv building, broken-manifest reporting, and a real
/analysis-tools run whose columns must equal the script's own CSV output.
The end-to-end part is skipped if morfeus is not installed.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import plugins

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE.parents[2] / "plugins" / "nhc_buried_volume"
NOT_NHC = "3\nwater, O first so N-C-N check fails\nO 0 0 0\nH 0.96 0 0\nH -0.24 0.93 0\n"


def check_discovery_and_command() -> None:
    tools, errors = plugins.discover_plugins()
    assert not errors, errors
    tool = tools["nhc_buried_volume"]
    assert tool["plugin"]["dir"] == str(EXAMPLE)

    cmd, out = plugins.plugin_command(
        tool, {"distance": 2.5, "exclude_hs": True}, Path("/x"), Path("/j")
    )
    assert cmd[:7] == [
        sys.executable, f"{EXAMPLE}/nhc_buried_volume.py",
        "-i", "/x", "-o", "/j/nhc_buried_volume.csv", "--include-opt",
    ], cmd
    assert out == Path("/j/nhc_buried_volume.csv")
    assert cmd[cmd.index("--distance") + 1] == "2.5"
    assert cmd[cmd.index("--bisector") + 1] == "external"  # manifest default
    assert "--exclude-hs" in cmd

    cmd, _ = plugins.plugin_command(tool, {"exclude_hs": False}, Path("/x"), Path("/j"))
    assert "--exclude-hs" not in cmd


def check_broken_manifest_reported() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad"
        bad.mkdir()
        (bad / "plugin.json").write_text(json.dumps({"id": "bad", "name": "Bad"}))
        dup = Path(tmp) / "dup"
        dup.mkdir()
        (dup / "plugin.json").write_text((EXAMPLE / "plugin.json").read_text())
        old = os.environ.get("MOLCRAFT_PLUGINS_DIR")
        os.environ["MOLCRAFT_PLUGINS_DIR"] = os.pathsep.join([str(EXAMPLE.parent), tmp])
        try:
            tools, errors = plugins.discover_plugins()
        finally:
            if old is None:
                os.environ.pop("MOLCRAFT_PLUGINS_DIR")
            else:
                os.environ["MOLCRAFT_PLUGINS_DIR"] = old
    assert list(tools) == ["nhc_buried_volume"], tools
    msgs = {Path(e["path"]).parent.name: e["error"] for e in errors}
    assert "command" in msgs["bad"] and "duplicate" in msgs["dup"], msgs


def check_end_to_end() -> None:
    try:
        import morfeus  # noqa: F401
    except ImportError:
        print("SKIP end-to-end: morfeus not installed")
        return
    from fastapi.testclient import TestClient

    import main

    xyzs = sorted(EXAMPLE.glob("examples/*.xyz"))
    ids = [p.stem for p in xyzs] + ["not_an_nhc"]
    xyz_by_id = {p.stem: p.read_text() for p in xyzs}
    xyz_by_id["not_an_nhc"] = NOT_NHC
    dataset = {
        "ids": ids,
        "columns": {"data_source": ["test"] * len(ids)},
        "meta": {},
        "xyzById": xyz_by_id,
    }
    client = TestClient(main.app)
    listed = client.get("/analysis-tools").json()
    assert "nhc_buried_volume" in [t["id"] for t in listed["tools"]]
    assert listed["plugin_errors"] == []

    resp = client.post(
        "/analysis-tools/nhc_buried_volume/run",
        json={"dataset": dataset, "params": {}},
    )
    assert resp.status_code == 200, resp.text
    cols = {c["name"]: c for c in resp.json()["addColumns"]}
    assert "percent_buried_volume" in cols and "quad_4_pVbur" in cols, list(cols)
    assert "center_x" not in cols and "bisector" not in cols, list(cols)
    # The failed molecule must leave numeric columns numeric, not categorical.
    assert cols["percent_buried_volume"]["kind"] == "numeric"
    assert cols["percent_buried_volume"]["values"][-1] is None
    assert "N-C-N" in cols["error"]["values"][-1]

    # Reference: the unchanged script run directly on the same files.
    with tempfile.TemporaryDirectory() as tmp:
        ref_csv = Path(tmp) / "ref.csv"
        subprocess.run(
            [sys.executable, str(EXAMPLE / "nhc_buried_volume.py"),
             "-i", str(EXAMPLE / "examples"), "-o", str(ref_csv)],
            check=True, capture_output=True,
        )
        ref = {Path(r["filename"]).stem: r for r in csv.DictReader(ref_csv.open())}
    for name in ("percent_buried_volume", "oct_0_pVbur", "quad_1_pVbur", "sterimol_B5"):
        for i, mol_id in enumerate(ids[:-1]):
            got = cols[name]["values"][i]
            assert abs(got - float(ref[mol_id][name])) < 1e-9, (name, mol_id, got)


if __name__ == "__main__":
    check_discovery_and_command()
    check_broken_manifest_reported()
    check_end_to_end()
    print("OK")
