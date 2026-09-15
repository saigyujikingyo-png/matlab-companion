#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v uv >/dev/null 2>&1; then
  python -m pip install --user 'uv==0.12.15'
  export PATH="$HOME/.local/bin:$PATH"
fi
uv sync --locked --python 3.12 --extra dev
printf '%s\n' 'Portable MATLAB Companion dependencies ready; no MATLAB or licence installed.'
