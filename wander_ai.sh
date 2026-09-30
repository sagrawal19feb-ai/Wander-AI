#!/usr/bin/env bash
cd "$(dirname "$0")"

export WANDER_HOME="$PWD/data"
export WANDER_MODELS="$PWD/models"
export TMPDIR="$PWD/data/.tmp"
export HF_HOME="$PWD/data/.cache/hf"
export PIP_CACHE_DIR="$PWD/data/.cache/pip"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
mkdir -p "$PWD/data/.tmp"

if [ ! -f "venv/engine.ready" ]; then
  ./install.sh auto
fi

if [ ! -x "venv/bin/python" ]; then
  echo "  Engine setup incomplete. Run ./install.sh first."
  exit 1
fi

exec ./venv/bin/python -B "$PWD/wander.py" "$@"
