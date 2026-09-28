"""External command plugins for the Analysis Tools tab.

A plugin is any folder with a ``plugin.json`` next to an unchanged script
that reads a folder of XYZ files and writes a CSV with an id/filename
column. Folders are listed in ``MOLCRAFT_PLUGINS_DIR`` (``os.pathsep``
separated, default ``<repo_root>/plugins``) and re-scanned on every call,
so dropping a folder in needs no restart. See docs/plugin-tools.md.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Collection

from tool_runtime import SUPPORTED_INPUT_TYPES

REPO_ROOT = Path(__file__).resolve().parents[3]


def plugin_dirs() -> list[Path]:
    """Return the plugin search folders from ``MOLCRAFT_PLUGINS_DIR``."""
    raw = os.environ.get("MOLCRAFT_PLUGINS_DIR") or str(REPO_ROOT / "plugins")
    return [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p]


def _load(manifest_path: Path) -> dict[str, Any]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("id", "name"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError(f'"{key}" must be a non-empty string')
    command = data.get("command")
    if not isinstance(command, list) or not command:
        raise ValueError('"command" must be a non-empty list of strings')
    inputs = data.get("inputs", [])
    for i, field in enumerate(inputs):
        if not isinstance(field.get("key"), str):
            raise ValueError(f'inputs[{i}] must define string "key"')
        if field.get("type") not in SUPPORTED_INPUT_TYPES:
            raise ValueError(f"inputs[{i}] has unsupported type {field.get('type')!r}")
    return {
        "id": data["id"],
        "name": data["name"],
        "description": data.get("description", ""),
        "inputs": inputs,
        "output": {"kind": "add_columns"},
        "plugin": {
            "dir": str(manifest_path.parent),
            "command": [str(c) for c in command],
            "python": data.get("python") or sys.executable,
            "ignoreColumns": list(data.get("ignoreColumns", [])),
        },
    }


def discover_plugins(
    reserved_ids: Collection[str] = (),
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Scan the plugin folders.

    Args:
        reserved_ids: Built-in tool ids a plugin may not shadow.

    Returns:
        (tools by id, list of {"path", "error"} for rejected manifests).
    """
    tools: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    for root in plugin_dirs():
        for manifest_path in sorted(root.glob("*/plugin.json")):
            try:
                tool = _load(manifest_path)
                if tool["id"] in reserved_ids or tool["id"] in tools:
                    raise ValueError(f"duplicate tool id {tool['id']!r}")
                tools[tool["id"]] = tool
            except Exception as exc:
                errors.append({"path": str(manifest_path), "error": str(exc)})
    return tools, errors


def plugin_command(
    tool: dict[str, Any],
    params: dict[str, Any],
    xyz_dir: Path,
    job_dir: Path,
) -> tuple[list[str], Path]:
    """Build the argv for one plugin run.

    Placeholders ``{python}``, ``{plugin_dir}``, ``{xyz_dir}``,
    ``{output_csv}``, ``{job_dir}`` and ``{<input key>}`` are substituted;
    inputs declaring ``"arg"`` are appended as ``arg value`` (booleans as a
    bare flag when true, empty values skipped).
    """
    plugin = tool["plugin"]
    output_csv = job_dir / f"{tool['id']}.csv"
    values = {f["key"]: params.get(f["key"], f.get("default")) for f in tool["inputs"]}

    def text(value: Any) -> str:
        if isinstance(value, list):
            return ",".join(str(v) for v in value)
        return "" if value is None else str(value)

    subs = {
        "{python}": plugin["python"],
        "{plugin_dir}": plugin["dir"],
        "{xyz_dir}": str(xyz_dir),
        "{output_csv}": str(output_csv),
        "{job_dir}": str(job_dir),
        **{f"{{{k}}}": text(v) for k, v in values.items()},
    }
    cmd = []
    for token in plugin["command"]:
        for placeholder, value in subs.items():
            token = token.replace(placeholder, value)
        cmd.append(token)

    for field in tool["inputs"]:
        arg, value = field.get("arg"), values.get(field["key"])
        if not arg:
            continue
        if field["type"] == "boolean":
            if value is True or str(value).lower() in {"1", "true", "yes", "on"}:
                cmd.append(arg)
        elif text(value) != "":
            cmd += [arg, text(value)]
    return cmd, output_csv
