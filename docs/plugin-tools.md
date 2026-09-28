# Plug-in Tools

There are two ways to plug your own property evaluation into the app:

| | **External command plugins** (recommended) | **In-process tools** |
|---|---|---|
| Lives in | any folder you choose, outside the package | `backend/tools/<id>/` inside the package |
| You write | a `plugin.json` next to your **unchanged** script | a `runner.py` adapter using the app's Python API |
| Runs as | a background job in the **Analysis tools** tab (log, cancel, queue, apply) | a synchronous call in the **Plug-in tools** tab |
| Python env | any (set `"python"` to another conda env) | the backend's env |
| Fits | eval scripts that take a folder of XYZ files and write a CSV | quick in-memory transforms (e.g. PCA of existing columns) |

## External command plugins

If your script already looks like `my_eval.py -i <xyz folder> -o <result.csv>`, it can become a plugin
without changing a line of it. The backend writes the selected molecules as `.xyz` files into a job folder,
runs your command, and merges the CSV back into the dataset by molecule ID.

### Where plugins live

The backend scans every folder in `MOLCRAFT_PLUGINS_DIR` for `*/plugin.json` (several folders are separated by
`:` on Linux/macOS or `;` on Windows). The default is `<repo_root>/plugins`. You can set the variable in any of the
`.env` files described in [Installation](installation.md):

```bash
MOLCRAFT_PLUGINS_DIR=/home/me/my_plugins:/shared/group_plugins
```

The folders are re-scanned whenever the Analysis tools tab loads its tool list, so a new plugin shows up after a
page reload, without restarting the backend. Manifests that fail to load are reported in the `plugin_errors` field
of `GET /analysis-tools`.

### Worked example: NHC buried volume

The repository ships `plugins/nhc_buried_volume/` as a complete example. It computes %V<sub>bur</sub>,
octant and quadrant %V<sub>bur</sub>, the N–C–N angle and Sterimol parameters of N-heterocyclic carbenes with
[Morfeus](https://digital-chemistry-laboratory.github.io/morfeus/). The sphere is centered on a dummy metal atom
placed along the N–C–N bisector.

```
plugins/nhc_buried_volume/
  plugin.json             ← how to call the script + UI inputs
  nhc_buried_volume.py    ← the original stand-alone script, unchanged
  examples/*.xyz          ← three NHCs to try it on
```

The script is an ordinary CLI (`python nhc_buried_volume.py -i refs/ -o out.csv --distance 2.0 ...`) that expects
atoms 1–3 of each XYZ to be N, C (carbene), N. Its `plugin.json`:

```json
{
  "id": "nhc_buried_volume",
  "name": "NHC buried volume (Morfeus)",
  "description": "Steric descriptors of N-heterocyclic carbenes ...",
  "command": [
    "{python}", "{plugin_dir}/nhc_buried_volume.py",
    "-i", "{xyz_dir}", "-o", "{output_csv}", "--include-opt"
  ],
  "ignoreColumns": ["bisector", "center_x", "center_y", "center_z", "..."],
  "inputs": [
    { "key": "distance", "label": "Metal-carbene distance (Å)", "type": "float", "default": 2.0, "arg": "--distance" },
    { "key": "bisector", "label": "N-C-N bisector", "type": "select",
      "options": ["external", "internal"], "default": "external", "arg": "--bisector" },
    { "key": "exclude_hs", "label": "Exclude hydrogens", "type": "boolean", "default": false, "arg": "--exclude-hs" }
  ]
}
```

To use it:

1. Install the script's dependency into the backend env: `pip install morfeus-ml` (it is already listed in
   `environment.yml`).
2. Load a dataset whose XYZ files are NHCs. For a quick try, use the files in `plugins/nhc_buried_volume/examples/`.
3. In **Analysis tools**, pick **NHC buried volume (Morfeus)**, set the parameters, and **Add to queue** → **Run**.
4. When the job completes, **Apply results** adds `percent_buried_volume`, `oct_0_pVbur` … `oct_7_pVbur`,
   `quad_1_pVbur` … `quad_4_pVbur`, `sterimol_L`/`B1`/`B5` and related columns. Molecules that fail (e.g. not N–C–N
   first) get empty values plus a text entry in the `error` column.

### `plugin.json` reference

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique tool id. Must not clash with a built-in analysis tool. |
| `name` | yes | Label shown in the tool picker. |
| `description` | no | Shown under the tool picker. |
| `command` | yes | The argv list to run. Placeholders are substituted (see below). |
| `python` | no | Interpreter used for `{python}`. The default is the backend's own Python. Point it at another conda env to keep the script's dependencies separate. |
| `inputs` | no | UI fields, same schema as in-process tools (`string`, `float`, `integer`, `boolean`, `select`, …, with `label`, `default`, `options`, `help`), plus an optional `arg`. |
| `ignoreColumns` | no | CSV columns not to add to the dataset (e.g. settings the script echoes on every row). |

Placeholders in `command`:

| Placeholder | Value |
|---|---|
| `{python}` | the `python` field, or the backend's interpreter |
| `{plugin_dir}` | the folder containing `plugin.json` |
| `{xyz_dir}` | the job folder holding the selected molecules as `.xyz` files |
| `{output_csv}` | `<job_dir>/<id>.csv`, where the script should write its CSV |
| `{job_dir}` | the job's working folder (also the process's working directory) |
| `{<input key>}` | the value of that input, for scripts that take positional arguments |

Each input with an `arg` is appended to the command automatically: `arg value` for normal inputs, and just
`arg` for a `boolean` that is true. Empty values are skipped.

### What the script must produce

- A CSV at `{output_csv}`. If it isn't there, the backend uses the first `*.csv` it finds in the job folder.
- One row per molecule, with a column identifying the input file: any of `filename`, `file`, `path`, `xyz_file`,
  `id`, `mol_id`, `name`. The value can be the file name, the full path, or the stem. The staged files are named
  `mol_<index>__<molecule id>.xyz`, so read the names from the folder rather than assuming the dataset IDs.
- Every other column becomes a dataset column: numeric if all non-empty values parse as numbers, categorical
  otherwise. Columns holding list-like vectors become descriptors. If a name already exists in the dataset, it is
  prefixed with the plugin id.
- A non-zero exit code fails the job. Everything the script prints goes to the job log (terminal button in the
  Analysis queue).

## In-process tools

The **Plug-in tools** tab exposes custom external property predictors — docking workflows, QSAR models, FEP surrogates, or any scoring function that can be wrapped in a Python function.


### Using a plug-in

1. Open the **Plug-in tools** tab.
2. Select a tool from the list. Its input fields are rendered automatically from the manifest.
3. Fill in the required parameters and click **Run tool**.
4. Results are applied to the dataset: `add_columns` tools add new visible columns; `add_descriptor` tools store a hidden per-molecule vector and add a visible `true`/`false` presence column with the descriptor's name.

### Adding a plug-in

Drop a directory under `webapp/database-explorer-lite/backend/tools/<tool_id>/` containing two files:

```
<tool_id>/
  manifest.json       ← declares the tool's inputs and output format
  runner.py            ← defines run_tool(dataset, params), called in-process
  requirements.txt    ← optional, Python deps (not auto-installed — see below)
```

The backend re-scans `backend/tools/` on every request to `/tools` and `/tools/{tool_id}/run`, so no backend restart is needed for it to execute a new tool. The tab's tool list, however, is normally built into the frontend bundle at build time (Vite glob-imports `backend/tools/*/manifest.json`); it only falls back to the live `/tools` endpoint when that bundled list is empty. In practice, rebuild the frontend (`npm run build`, or reload under `FRONTEND_DEV=1 ./dev.sh`) after adding a tool so it appears in the tab.

If `requirements.txt` is present, install its packages manually into the backend's Python environment — the app does not install them automatically.

#### `manifest.json` structure

```json
{
  "manifestVersion": 1,
  "id": "my_tool",
  "name": "My scoring function",
  "description": "One-line description shown in the UI.",
  "needsXyz": true,
  "inputs": [
    {
      "key": "threshold",
      "label": "Score threshold",
      "type": "float",
      "default": 0.5,
      "required": true
    }
  ],
  "output": {
    "kind": "add_columns"
  }
}
```

**`output.kind`** is descriptive metadata shown alongside the tool; the backend actually decides how to apply results based on which keys (`addColumns` and/or `addDescriptor`) the runner's return value contains, not on this field. Set it to document intent:

| Value | Effect |
|---|---|
| `add_columns` | Runner is expected to return `addColumns` — new visible dataset columns |
| `add_descriptor` | Runner is expected to return `addDescriptor` — a hidden per-molecule vector plus an auto-added presence column |

**`needsXyz`**: if `true`, the frontend loads each molecule's XYZ text and sends it to the backend as `dataset.xyzById` (a dict of `mol_id → xyz text`). If omitted or `false`, `xyzById` is sent empty.

See `webapp/database-explorer-lite/backend/tools/external_tool_manifest_reference.md` in the repository for the full list of supported input types (`string`, `text`, `integer`, `float`, `boolean`, `select`, `multiselect`, `slider_int`, `slider_float`, `column`, `column_multi`, `column_numeric`, `column_categorical`, `column_multi_numeric`, `column_multi_categorical`) and field properties (`options`, `min`/`max`/`step`, `help`).

#### `runner.py` contract

The backend imports `runner.py` as a Python module in-process (no subprocess, no CLI flags) and calls a required function:

```python
def run_tool(dataset, params):
    ...
```

`dataset` is a dict with keys `ids`, `columns`, `meta`, `xyzById` (only populated when `needsXyz: true`), and `descriptors` (previously stored hidden descriptor vectors, keyed by descriptor name). `params` holds the user-filled values keyed by each input's `key`, coerced to the declared type.

It must return a dict containing at least one of `message`, `warnings`, `addColumns`, `addDescriptor`, or `stats`. Minimal example that adds a new numeric column:

```python
def run_tool(dataset, params):
    ids = dataset.get("ids", [])
    threshold = params.get("threshold", 0.5)

    # ... compute one score per id ...
    scores = [0.0 for _ in ids]

    return {
        "message": f"Scored {len(ids)} molecules.",
        "addColumns": [
            {"name": "score", "kind": "numeric", "values": scores}
        ],
    }
```

Rules enforced by the backend:

- `addColumns[i].values` must have exactly one entry per dataset row (`kind: "numeric"` → int/float/`None`; `kind: "categorical"` → string/`None`), and the column name must not already exist.
- `addDescriptor.valuesById` maps a subset of dataset ids to equal-length numeric vectors; the descriptor name must not collide with an existing column or descriptor.
- Raising a Python exception (or an unhandled `ModuleNotFoundError` for a missing dependency) fails the run with an error message shown in the UI; nothing partial is applied.

See `webapp/database-explorer-lite/backend/tools/external_tool_manifest_reference.md` for the full manifest and result schema, and `webapp/database-explorer-lite/backend/tools/{row_index,basic_geom_descriptor,PCA}/` for complete working examples of both output modes.
