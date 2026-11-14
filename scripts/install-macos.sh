#!/usr/bin/env bash
# One-step install / update of AutomaticMolCraft on an Apple-Silicon Mac.
#
#   ./scripts/install-macos.sh             # create (or update) the "molcraft" conda env, build the UI, run doctor
#   ./scripts/install-macos.sh --dry-run   # print what would run, change nothing
#   ./scripts/install-macos.sh --help
#
# After it finishes:   conda activate molcraft && automolcraft serve
#                      (`automolcraft service --help` explains how to start it at every login)
#
# What it does, in order:
#   1. checks this is an Apple-Silicon Mac and finds conda (it does not install conda for you)
#   2. creates the env from environment-macos.yml -- or, if the env exists, re-applies that file's
#      pip packages (an editable MolCraftDiffusion checkout is left alone and only compared to the pin)
#   3. builds the frontend, writes a commented .env if you have none, creates models/
#   4. runs `automolcraft doctor`
#
# Conda's Anaconda `defaults` channel asks you to accept a Terms of Service before it will create
# anything. This script never accepts it for you: every conda call uses --override-channels
# -c conda-forge instead, so `defaults` is not consulted at all.
#
# Written for the bash 3.2 that ships with macOS.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/environment-macos.yml"
APP_DIR="$REPO_ROOT/webapp/database-explorer-lite"
MAIN_PY="$APP_DIR/backend/main.py"

ENV_NAME="molcraft"
DRY_RUN=0
BUILD_FRONTEND=1

usage() {
  sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options:
  --env NAME       conda environment name (default: molcraft)
  --no-frontend    skip building the web UI
  --dry-run        print the commands instead of running them
  -h, --help       show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --env)          [ $# -ge 2 ] || { echo "error: --env needs a name" >&2; exit 2; }; ENV_NAME="$2"; shift 2 ;;
    --no-frontend)  BUILD_FRONTEND=0; shift ;;
    --dry-run)      DRY_RUN=1; shift ;;
    -h|--help)      usage; exit 0 ;;
    *)              echo "error: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[install] warning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m[install] error:\033[0m %s\n' "$*" >&2; exit 1; }

# Run a command, or only print it under --dry-run.
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  + %s\n' "$*"
  else
    "$@"
  fi
}

# ---------------------------------------------------------------------------
# 1. Preflight
# ---------------------------------------------------------------------------
[ "$(uname -s)" = "Darwin" ] || die "this script is for macOS; on Linux/WSL use environment.yml (see docs/installation.md)"
[ "$(uname -m)" = "arm64" ]  || die "Apple Silicon (arm64) is required: the pinned PyTorch 2.6 has no build for Intel Macs"
[ -f "$ENV_FILE" ]           || die "missing $ENV_FILE -- run this from a clone of the repository"
[ -f "$MAIN_PY" ]            || die "missing $MAIN_PY -- run this from a clone of the repository"

macos_major="$(sw_vers -productVersion | cut -d. -f1)"
if [ "$macos_major" -lt 13 ] 2>/dev/null; then
  warn "macOS $(sw_vers -productVersion): the Apple GPU (MPS) backend needs macOS 12.3+, and 13+ is recommended"
fi

find_conda() {
  if command -v conda >/dev/null 2>&1; then command -v conda; return 0; fi
  local c
  for c in \
    "$HOME/miniforge3/bin/conda" "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" \
    "$HOME/mambaforge/bin/conda" "/opt/homebrew/Caskroom/miniforge/base/bin/conda" \
    "/opt/homebrew/Caskroom/miniconda/base/bin/conda" "/opt/miniconda3/bin/conda" "/opt/homebrew/bin/conda"; do
    if [ -x "$c" ]; then echo "$c"; return 0; fi
  done
  return 1
}

CONDA="$(find_conda)" || die "conda not found. Install Miniforge (conda-forge only, no Terms-of-Service prompt):
    brew install --cask miniforge
  or see https://github.com/conda-forge/miniforge , then run this script again."
say "conda: $CONDA ($("$CONDA" --version 2>&1))"

# Prefix of the conda env named $1, or empty. `conda env list` rows are: name [*] path
env_prefix() {
  "$CONDA" env list 2>/dev/null | awk -v n="$1" '$1 == n { print $NF }' | head -n 1
}

# What kind of install is distribution $1 in env python $2: missing | editable:<dir> | vcs:<sha> | other
dist_origin() {
  "$2" - "$1" <<'PY'
import json, sys
from importlib import metadata
from urllib.parse import unquote
try:
    d = metadata.distribution(sys.argv[1])
except metadata.PackageNotFoundError:
    print("missing"); raise SystemExit
raw = d.read_text("direct_url.json")
info = json.loads(raw) if raw else {}
if info.get("dir_info", {}).get("editable"):
    print("editable:" + unquote(info.get("url", "")).replace("file://", ""))
elif "vcs_info" in info:
    print("vcs:" + info["vcs_info"].get("commit_id", ""))
else:
    print("other")
PY
}

# The pip: block of the environment file, one requirement per line (valid for `pip install -r`).
pip_requirements() {
  awk '
    /^[[:space:]]*-[[:space:]]+pip:[[:space:]]*$/ { inpip = 1; next }
    inpip && /^[[:space:]]*#/                      { next }
    inpip && /^[[:space:]]*-[[:space:]]/ {
      line = $0; sub(/^[[:space:]]*-[[:space:]]+/, "", line); print line; next
    }
    inpip && /^[^[:space:]]/                       { inpip = 0 }
  ' "$1"
}

PINNED_COMMIT="$(sed -n -E 's/^MOLCRAFT_PINNED_COMMIT = "([0-9a-f]{40})".*/\1/p' "$MAIN_PY" | head -n 1)"
[ -n "$PINNED_COMMIT" ] || warn "could not read MOLCRAFT_PINNED_COMMIT from $MAIN_PY"

# ---------------------------------------------------------------------------
# 2. Create or update the environment
# ---------------------------------------------------------------------------
PREFIX="$(env_prefix "$ENV_NAME")"
cd "$REPO_ROOT"   # the env file installs this app with a relative `-e .[all]`

if [ -z "$PREFIX" ]; then
  say "creating conda env '$ENV_NAME' from environment-macos.yml (downloads a few GB; takes several minutes)"
  run "$CONDA" create -y -n "$ENV_NAME" --override-channels -c conda-forge --file "$ENV_FILE"
  if [ "$DRY_RUN" -eq 1 ]; then
    PREFIX="<prefix of $ENV_NAME>"
  else
    PREFIX="$(env_prefix "$ENV_NAME")"
    [ -n "$PREFIX" ] || die "the env was created but conda does not list it; check \`conda env list\`"
  fi
else
  say "env '$ENV_NAME' already exists at $PREFIX -- updating its pip packages"
  PY="$PREFIX/bin/python"
  [ -x "$PY" ] || die "$PY not found; remove the env and run again"

  tmp_req="$(mktemp -t automolcraft-req)"
  trap 'rm -f "$tmp_req"' EXIT
  pip_requirements "$ENV_FILE" > "$tmp_req"

  origin="$(dist_origin molcraftdiffusion "$PY")"
  case "$origin" in
    editable:*)
      src="${origin#editable:}"
      head_commit="$(git -C "$src" rev-parse HEAD 2>/dev/null || echo unknown)"
      say "MolCraftDiffusion is an editable install from $src -- leaving it as is"
      if [ -n "$PINNED_COMMIT" ] && [ "$head_commit" != "$PINNED_COMMIT" ]; then
        warn "that checkout is at ${head_commit:0:10} but this app is pinned to ${PINNED_COMMIT:0:10};"
        warn "update it with:  git -C '$src' fetch && git -C '$src' checkout ${PINNED_COMMIT:0:10}"
      else
        say "checkout is at the pinned commit ${PINNED_COMMIT:0:10}"
      fi
      # Do not replace a development checkout with the pinned git copy (or its Mac shims).
      grep -v -E '^(molcraftdiffusion(\[[^]]*\])?|molcraft-mac-shims) @ ' "$tmp_req" > "$tmp_req.f" && mv "$tmp_req.f" "$tmp_req"
      ;;
    vcs:*)
      say "MolCraftDiffusion installed from git at ${origin#vcs:}; pinned: ${PINNED_COMMIT:0:10}"
      ;;
    *)
      say "MolCraftDiffusion: $origin -- installing the pinned commit"
      ;;
  esac

  if [ -s "$tmp_req" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      say "would run: $PY -m pip install --upgrade -r <requirements below>"
      sed 's/^/    /' "$tmp_req"
    else
      "$PY" -m pip install --upgrade -r "$tmp_req"
    fi
  fi
fi

AUTOMOLCRAFT="$PREFIX/bin/automolcraft"

# ---------------------------------------------------------------------------
# 3. Frontend, .env, models/
# ---------------------------------------------------------------------------
if [ "$BUILD_FRONTEND" -eq 1 ]; then
  say "building the web UI"
  run "$AUTOMOLCRAFT" build-frontend
else
  say "skipping the frontend build (--no-frontend)"
fi

env_path="$APP_DIR/.env"
if [ ! -f "$REPO_ROOT/.env" ] && [ ! -f "$env_path" ] && [ ! -f "$APP_DIR/backend/.env" ]; then
  say "writing a commented $env_path (every setting is optional)"
  if [ "$DRY_RUN" -eq 0 ]; then
    cat > "$env_path" <<EOF
# AutomaticMolCraft local settings. Every variable is optional; unset ones fall back to
# <repo>/models, <repo>/outputs, <repo>/presets, ... See docs/installation.md.
#
# Where the app looks for generation checkpoints (folders that contain edm_chem.pkl):
# MOLCRAFT_MODELS_DIR=$REPO_ROOT/models
EOF
  fi
fi
run mkdir -p "$REPO_ROOT/models"

# ---------------------------------------------------------------------------
# 4. Doctor
# ---------------------------------------------------------------------------
say "checking the install"
doctor_status=0
if [ "$DRY_RUN" -eq 1 ]; then
  run "$AUTOMOLCRAFT" doctor
else
  "$AUTOMOLCRAFT" doctor || doctor_status=$?
fi

cat <<EOF

Next steps
  Start the app:            $AUTOMOLCRAFT serve
                            (or: conda activate $ENV_NAME && automolcraft serve)
  Start it at every login:  $AUTOMOLCRAFT service install
  Pretrained models:        none are downloaded automatically (the Hugging Face repo is gated).
                            Accept the terms at https://huggingface.co/pregH/MolecularDiffusion, then
                              $PREFIX/bin/pip install -U huggingface_hub
                              $PREFIX/bin/hf auth login
                              $PREFIX/bin/hf download pregH/MolecularDiffusion --include 'models/EDM_qm9/*' --local-dir '$REPO_ROOT'
                            (the files land in $REPO_ROOT/models/EDM_qm9, where the app looks by default)
EOF

if [ "$doctor_status" -ne 0 ]; then
  warn "doctor reported missing required items (see above)"
  exit "$doctor_status"
fi
