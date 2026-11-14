# Installation

There are two routes. The **recommended** one installs everything from one environment file and
gives you the `automolcraft` command. The **manual** route is the step-by-step install used with
`./dev.sh`; it still works and is kept below.

## Recommended: environment file + `automolcraft`

### 1. Clone and create the environment

=== "Linux / WSL (NVIDIA GPU)"

    ```bash
    git clone https://github.com/pregHosh/AutomaticMolCraftt
    cd AutomaticMolCraftt
    conda env create -f environment.yml
    conda activate molcraft
    ```

=== "macOS (Apple Silicon)"

    ```bash
    git clone https://github.com/pregHosh/AutomaticMolCraftt
    cd AutomaticMolCraftt
    ./scripts/install-macos.sh     # creates the env, builds the UI, runs doctor (details below)
    conda activate molcraft
    ```

    Without the script: `conda create -n molcraft --override-channels -c conda-forge --file environment-macos.yml`.

The environment file installs, from conda-forge and pip:

- xTB 6.7.1, xtb-python, OpenBabel and Node.js
- MolCraftDiffusion at the commit this app is pinned to (see [Version pin](#version-pin))
- the analysis-tool packages (PoseBusters, open3d, dscribe, UMAP, …)
- this web app itself, as an editable install that provides the `automolcraft` command

The repository stays where you cloned it: jobs, outputs and presets are written inside it unless you
move them with [environment variables](#environment-variables).

!!! tip "Conda stops with a “Terms of Service have not been accepted” error"
    Miniconda and Anaconda list Anaconda's `defaults` channel in their config, and recent conda refuses
    to create any environment until its Terms of Service are accepted, even though these environment
    files only use conda-forge. Either accept them (`conda tos accept`), or skip `defaults` for this one
    command (conda 26 or newer):

    ```bash
    conda create -n molcraft --override-channels -c conda-forge --file environment.yml   # or environment-macos.yml
    ```

    [Miniforge](https://github.com/conda-forge/miniforge) uses conda-forge only and never shows this error.

!!! note "CPU-only Linux"
    Edit `environment.yml` before creating the environment: change the `--find-links` URL to
    `https://data.pyg.org/whl/torch-2.6.0+cpu.html`, change `molcraftdiffusion[gpu]` to
    `molcraftdiffusion[cpu]`, and add the line `--extra-index-url https://download.pytorch.org/whl/cpu`.

### 2. Check the setup

```bash
automolcraft doctor
```

`doctor` checks the environment without starting anything and prints one line per item, with a
fix for anything missing:

```text
Web app
  ✓ Python                   3.11.16 (…/envs/molcraft/bin/python)
  ✓ fastapi                  0.114.2
  …
  ✓ frontend build           webapp/database-explorer-lite/frontend/dist
  ✓ .env                     webapp/database-explorer-lite/.env

MolCraftDiffusion
  ✓ MolCraftDiff CLI         …/envs/molcraft/bin/MolCraftDiff
  ✓ version                  1.13.0 (pinned 1.13.0)
  ✓ torch device             Apple MPS · torch 2.6.0

Analysis tools (optional)
  ✓ xtb                      …/envs/molcraft/bin/xtb
  ⚠ umap-learn               missing — needed for UMAP projection
      → pip install -e '.[umap]'

Models
  ⚠ generation models        none in …/AutomaticMolCraftt/models
      → download from https://huggingface.co/pregH/MolecularDiffusion or set MOLCRAFT_MODELS_DIR in .env
```

`✗` marks something the app cannot start without; `⚠` marks an optional feature that will not work
until you install what it names. The command exits with status 1 when any `✗` is present.

### 3. Download pretrained models

Models are hosted on Hugging Face at [pregH/MolecularDiffusion](https://huggingface.co/pregH/MolecularDiffusion).
Place the checkpoint folders under `models/` at the repository root, or point `MOLCRAFT_MODELS_DIR`
at them (see [Environment variables](#environment-variables)).

Each checkpoint folder must contain `edm_chem.pkl`. The optional `edm_stat.pkl` enables conditional
generation statistics.

### 4. Launch

```bash
automolcraft serve
```

The first run builds the frontend (about a minute); after that the app starts in a few seconds and
opens `http://127.0.0.1:8000` in your browser. Stop it with Ctrl+C.

`automolcraft` works from any directory once the environment is active, and always runs the backend
with the Python of the environment it is installed in.

### Launch options

| `automolcraft serve …` | Same with `./dev.sh` | Effect |
|---|---|---|
| *(no flags)* | `./dev.sh` | Backend on `:8000`, serves the pre-built frontend |
| `--port 9000` | `BACKEND_PORT=9000 ./dev.sh` | Run the backend on another port |
| `--host 0.0.0.0` | `BACKEND_HOST=0.0.0.0 ./dev.sh` | Reachable from other machines (e.g. a GPU server) |
| `--dev` | `FRONTEND_DEV=1 ./dev.sh` | Also run the Vite hot-reload server on `:5173` (frontend development) |
| `--reload` | `BACKEND_RELOAD=1 ./dev.sh` | Restart the backend when Python files change |
| `--rebuild` | — | Rebuild the frontend, e.g. after `git pull` |
| `--no-browser` | — | Do not open a browser tab |

`automolcraft build-frontend` rebuilds the frontend without starting the app.

---

## macOS (Apple Silicon)

The app runs natively on M-series Macs; `environment-macos.yml` sets it up. What differs from Linux:

- **GPU**: models run on the Apple GPU through PyTorch's MPS backend. CUDA does not exist on macOS, so
  the CUDA options in the analysis tools (t-SNE on CUDA, UMA on CUDA) do not apply; the CPU defaults work.
- **MolCraftDiffusion**: both environment files pin the same commit. Its `[mac]` extra and the
  `mac_shims` package are what make it run on Apple Silicon.
- **PyG extensions**: `torch_scatter` / `torch_cluster` are replaced by pure-torch shims from the
  MolCraftDiffusion repository, which run on MPS.
- **Speed**: generation and training work but are slower than on a CUDA GPU, and memory is shared with
  the system.
- **Training families**: the ones whose models use float64 (Regression, SSL-3D and Guidance with eSEN, and
  VAE (Transformer)) stop at start-up on MPS. See [Model training](training.md#task-family).
- **`FRONTEND_DEV=1 ./dev.sh`** fails on the bash 3.2 that ships with macOS (`wait -n`). Use
  `automolcraft serve --dev`, or install a newer bash (`brew install bash`).

### One-step install

```bash
./scripts/install-macos.sh             # create or update the "molcraft" env, build the UI, run doctor
./scripts/install-macos.sh --dry-run   # print the commands without running them
```

It needs conda ([Miniforge](https://github.com/conda-forge/miniforge) is the simplest) and an
Apple-Silicon Mac, and it does not install conda for you. In order, it:

- creates the environment from `environment-macos.yml` with `--override-channels -c conda-forge`, so
  Anaconda's Terms-of-Service prompt never appears and nothing is accepted on your behalf;
- on an **existing** environment, re-applies the file's pip packages. If MolCraftDiffusion there is an
  editable install (a development checkout) it is left alone and only compared with the pinned commit;
- builds the frontend, writes a commented `.env` if you have none, creates `models/`, and finishes with
  `automolcraft doctor`.

It does not download model checkpoints, because the Hugging Face repository is gated. Accept the terms on
the [model page](https://huggingface.co/pregH/MolecularDiffusion), then from the repository root:

```bash
pip install -U huggingface_hub
hf auth login
hf download pregH/MolecularDiffusion --include 'models/EDM_qm9/*' --local-dir .
```

### Start at login

```bash
automolcraft service install     # start now and at every login (a launchd LaunchAgent)
automolcraft service status      # installed? serving?
automolcraft service logs        # end of ~/Library/Logs/automolcraft/serve.log
automolcraft service restart     # e.g. after git pull
automolcraft service uninstall
```

`service install --port 9000` changes the port and `service install --print` shows the generated plist
without installing anything. Nothing is installed until you run `service install`. The service listens on
`127.0.0.1`; `--host 0.0.0.0` exposes it to your network, and since the app can read files on this Mac by
path and has no login, do that only on a network you trust.

### Updating

```bash
git pull
./scripts/install-macos.sh       # re-applies the pinned MolCraftDiffusion commit and rebuilds the UI
automolcraft service restart     # only if you use the service
```

---

## Manual install

The step-by-step route, launched with `./dev.sh`.

### 1. Create the environment

```bash
conda create -n molcraft python=3.11 -y
conda activate molcraft
```

Install required system-level chemistry packages via conda-forge:

```bash
conda install -c conda-forge xtb==6.7.1 openbabel -y
```

`xtb` is a semi-empirical quantum chemistry package (used in [Analysis Tools](analysis-tools.md)). `openbabel` handles 2D structure rendering in the app.

### 2. Install MolCraftDiffusion

Install from the pinned commit (see [Version pin](#version-pin)); it is not on PyPI:

```bash
MOLCRAFT_REF=108dc45b11b9d73cca2c16f2d1d6b0f781c4aede
```

**GPU (CUDA 12.4, PyTorch 2.6):**

```bash
pip install "molcraftdiffusion[gpu] @ git+https://github.com/pregHosh/MolCraftDiffusion@${MOLCRAFT_REF}" \
    --find-links https://data.pyg.org/whl/torch-2.6.0+cu124.html
```

**CPU-only:**

```bash
pip install "molcraftdiffusion[cpu] @ git+https://github.com/pregHosh/MolCraftDiffusion@${MOLCRAFT_REF}" \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    --find-links https://data.pyg.org/whl/torch-2.6.0+cpu.html
```

!!! warning "MolCraftDiffusion's `[analyze]` extra downgrades pandas"
    `pip install 'molcraftdiffusion[analyze]'` pulls in `posecheck`, which pins `pandas==2.0.0`. That
    pandas is built for numpy 1 and fails with numpy 2 (`numpy.dtype size changed`). Install the
    analysis packages directly instead:
    `pip install 'posebusters>=0.5.1' morfeus-ml rmsd open3d dscribe umap-learn 'pandas>=2.3,<2.4'`.

### 3. Install the web app backend

```bash
pip install -r webapp/database-explorer-lite/backend/requirements.txt
```

### 4. Download pretrained models

As in [step 3 of the recommended route](#3-download-pretrained-models).

### 5. Configure environment variables (optional)

See [Environment variables](#environment-variables).

### 6. Build the frontend

Run once (or whenever frontend source files change):

```bash
cd webapp/database-explorer-lite/frontend
npm install
npm run build
```

`dev.sh` auto-runs this step if `frontend/dist` is absent or stale.

### 7. Launch

```bash
./dev.sh
```

Then open `http://localhost:8000` in your browser. See [Launch options](#launch-options) for the
`dev.sh` variables. `dev.sh` auto-detects the Python interpreter from `$VIRTUAL_ENV`, `$CONDA_PREFIX`,
or common `.venv`/`venv` paths; set `BACKEND_PYTHON=/path/to/python` to choose one explicitly.

---

## Environment variables

```bash
cp webapp/database-explorer-lite/.env.example webapp/database-explorer-lite/.env
```

All variables are optional. Both `automolcraft serve` and `./dev.sh` read the first `.env` found in the
repository root, `webapp/database-explorer-lite/`, or its `backend/` folder. Variables already set in
your shell take precedence.

| Variable | Default | Purpose |
|---|---|---|
| `MOLCRAFT_MODELS_DIR` | `<repo>/models` | Where the app looks for model checkpoints |
| `MOLCRAFT_OUTPUTS_DIR` | `<repo>/outputs` | Where generation and training job outputs are written |
| `MOLCRAFT_PLUGINS_DIR` | `<repo>/plugins` | Folders scanned for [external command plugins](plugin-tools.md#external-command-plugins) (`:`-separated) |
| `MOLCRAFT_ANALYSIS_WORK_DIR` | `<repo>/analysis_jobs` | Storage for async analysis jobs |
| `MOLCRAFT_PRESETS_DIR` | `<repo>/presets` | Persistent parameter presets |
| `MOLCRAFT_TRAIN_DB` | `<backend>/training_jobs.db` | SQLite file holding the training job list |
| `MOLCRAFT_CMD` | `MolCraftDiff` | CLI command name for the diffusion runner |
| `MOLCRAFT_UNLOCK_PASSWORD` | *(unset)* | Password for unlocking extended task families in the Model training tab (public families are always available) |

---

## Version pin

The app is pinned to MolCraftDiffusion **commit `108dc45b11b9d73cca2c16f2d1d6b0f781c4aede`
(version 1.13.0)** — an exact pin, not a minimum. The app names Hydra config groups (`tasks`,
`interference`) and `analyze` CLI flags that shift across upstream commits (flags get renamed or moved
to a different subcommand, not just added); a package that's ahead of or behind the pin can fail a job
partway through with a `MissingConfigException` or `no such option` rather than failing at startup.
This pin is **not on PyPI** — `pypi.org/project/molcraftdiffusion` lags it by several releases.

`automolcraft doctor` and `curl localhost:8000/healthz` both report the installed version and commit
against the pin. The pin lives in `webapp/database-explorer-lite/backend/main.py`
(`MOLCRAFT_PINNED_VERSION` / `MOLCRAFT_PINNED_COMMIT`) — this page, `environment.yml` and
`environment-macos.yml` must match those constants; bump them together and re-verify `TASK_FAMILIES` /
`TASK_TYPE_TO_TASKS_CONFIG` / the `analyze` CLI flags before moving the pin forward.

Two scripts in `webapp/database-explorer-lite/backend/` do that re-check, so run them after changing the
pin (with the new MolCraftDiffusion installed):

```bash
python test_task_families.py   # every task group exists, installed version == pin
python test_analysis_cmds.py   # every `analyze` flag the backend passes exists in the installed CLI
```
