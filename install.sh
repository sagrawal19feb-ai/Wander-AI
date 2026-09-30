#!/usr/bin/env bash
cd "$(dirname "$0")"

export WANDER_HOME="$PWD/data"
export WANDER_MODELS="$PWD/models"
export TMPDIR="$PWD/data/.tmp"
export HF_HOME="$PWD/data/.cache/hf"
export PIP_CACHE_DIR="$PWD/data/.cache/pip"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$PWD/data/.tmp"

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
VENV="$PWD/venv"
VP="$VENV/bin/python"

install_base() {
  echo
  echo "  Installing base engine..."
  if ! "$PY" -m venv "$VENV"; then
    echo "  Could not create the environment."
    echo "  On Debian/Ubuntu: sudo apt install python3 python3-venv"
    exit 1
  fi
  "$VP" -m pip install --upgrade pip >/dev/null || exit 1
  "$VP" -m pip install torch --index-url https://download.pytorch.org/whl/cpu --no-compile || exit 1
  "$VP" -m pip install transformers accelerate sentencepiece gguf rich prompt_toolkit --no-compile || exit 1
  echo ready > "$VENV/engine.ready"
  echo "  Done."
}

install_turbo() {
  [ -x "$VP" ] || { echo "  Install the base engine first."; exit 1; }
  echo
  echo "  Installing turbo engine..."
  "$VP" -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --no-compile || exit 1
  echo "  Done."
}

detect_cu() {
  "$VP" -c "import subprocess,re,shutil;o=subprocess.run(['nvidia-smi'],capture_output=True,text=True).stdout if shutil.which('nvidia-smi') else '';m=re.search(r'CUDA Version: (\d+)\.(\d+)',o);print('cu124' if m and (int(m.group(1)),int(m.group(2)))>=(12,4) else 'cu121' if m and (int(m.group(1)),int(m.group(2)))>=(12,1) else '')" 2>/dev/null
}

install_gpu() {
  [ -x "$VP" ] || { echo "  Install the base engine first."; exit 1; }
  echo
  CU="$(detect_cu)"
  if [ -z "$CU" ]; then
    echo "  No NVIDIA GPU/driver found (needs CUDA 12.1+) - will use CPU."
    return 0
  fi
  echo "  NVIDIA GPU detected - installing GPU engine ($CU)..."
  if "$VP" -m pip install llama-cpp-python --force-reinstall --only-binary :all: --extra-index-url "https://abetlen.github.io/llama-cpp-python/whl/$CU" --no-compile; then
    echo "  Done."
  else
    echo "  GPU engine skipped (no matching prebuilt wheel) - will use CPU."
  fi
}

install_all() {
  install_base
  install_turbo
  install_gpu
  echo "  All done."
}

if [ "$1" = "auto" ]; then
  install_all
  exit 0
fi

while true; do
  clear
  echo
  echo "  WANDER INSTALLER"
  echo
  if [ -f "$VENV/engine.ready" ]; then
    echo "  Base engine: installed"
  else
    echo "  Base engine: not installed"
  fi
  echo
  echo "  1. Base engine"
  echo "  2. Turbo engine"
  echo "  3. GPU engine (NVIDIA)"
  echo "  4. Everything (base + turbo + GPU)   [no prompts]"
  echo "  5. Exit"
  echo
  read -rp "  Option: " CHOICE
  case "$CHOICE" in
    1) install_base ;;
    2) install_turbo ;;
    3) install_gpu ;;
    4) install_all ;;
    5) exit 0 ;;
  esac
  echo
  read -rp "  Press Enter to continue..." _
done
