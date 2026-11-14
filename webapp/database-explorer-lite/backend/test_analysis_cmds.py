"""Check that every `MolCraftDiff analyze` flag this backend passes exists in the installed CLI.

_analysis_cmd_for_tool builds command lines by hand, so a flag renamed or moved upstream only
surfaces as `no such option` minutes into a job. Run this after bumping the MolCraftDiffusion pin
or touching _analysis_cmd_for_tool / ANALYSIS_TOOLS:

    python test_analysis_cmds.py

Skips when the MolCraftDiff CLI is not on PATH.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Representative params per built-in tool, chosen so every optional flag branch is exercised.
SAMPLES: dict[str, list[dict]] = {
    "validity_connectivity": [
        {"metrics": "posebuster", "recheck_topo": True, "mol_converter": "openbabel"},
        {"metrics": "core"},
        {"metrics": "geom_revised"},
    ],
    "druglike_metrics": [
        {},
        {"rdkit_rmsd": True, "rmsd_n_conf": 5, "mol_converter": "openbabel", "timeout": 5},
    ],
    "xyz_to_smiles": [{"bits": 1024}],
    "xtb_electronic_properties": [
        {"method": "2", "properties": "energy"},
        {"method": "1", "properties": "all", "charge": 1, "n_unpaired": 1, "solvent": "water",
         "n_jobs": 2, "timeout": 30, "corrected": False},
    ],
    "featurize": [
        {"backend": "soap", "autodetect": True},
        {"backend": "uma", "device": "cpu", "batch_size": 4},
    ],
    "xtb_geometry_optimization": [{"level": "gfn2", "charge": 0, "timeout": 60, "scale_factor": 1.3}],
}


def _flags(cmd: list[str]) -> list[str]:
    return [t for t in cmd if re.match(r"^--?[A-Za-z]", t)]


def main() -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    import main as backend

    # Same rule as the launcher: the CLI of the environment running this interpreter wins.
    search_path = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    cli = shutil.which(backend.MOLCRAFT_CMD, path=search_path)
    if cli is None:
        print(f"SKIP: {backend.MOLCRAFT_CMD} not on PATH")
        return 0

    missing_tools = sorted(set(SAMPLES) - set(backend.ANALYSIS_TOOLS))
    assert not missing_tools, f"SAMPLES names tools that no longer exist: {missing_tools}"
    untested = sorted(
        t for t in backend.ANALYSIS_TOOLS
        if t not in SAMPLES and t not in {"dimensionality_reduction", "predict_properties"}
    )
    assert not untested, f"add SAMPLES for new analysis tools: {untested}"

    help_cache: dict[str, str] = {}

    def help_for(sub: str) -> str:
        if sub not in help_cache:
            out = subprocess.run([cli, "analyze", sub, "--help"], capture_output=True, text=True, timeout=120)
            assert out.returncode == 0, f"`analyze {sub} --help` failed:\n{out.stdout}\n{out.stderr}"
            help_cache[sub] = out.stdout
        return help_cache[sub]

    checked = 0
    with tempfile.TemporaryDirectory() as td:
        xyz_dir = Path(td) / "xyz"
        job_dir = Path(td) / "job"
        xyz_dir.mkdir()
        job_dir.mkdir()
        for tool_id, variants in SAMPLES.items():
            for params in variants:
                cmd, _ = backend._analysis_cmd_for_tool(tool_id, params, xyz_dir, job_dir)
                assert cmd[:2] == [backend.MOLCRAFT_CMD, "analyze"], (tool_id, cmd)
                sub = cmd[2]
                text = help_for(sub)
                for flag in _flags(cmd[3:]):
                    pattern = rf"(?<![\w-]){re.escape(flag)}(?![\w-])"
                    assert re.search(pattern, text), (
                        f"{tool_id}: `analyze {sub}` has no option {flag!r} in molcraftdiffusion "
                        f"{backend._molcraft_version()}; command was: {' '.join(cmd)}"
                    )
                    checked += 1

    print(f"OK: {checked} flags across {len(SAMPLES)} tools exist in `{backend.MOLCRAFT_CMD} analyze`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
