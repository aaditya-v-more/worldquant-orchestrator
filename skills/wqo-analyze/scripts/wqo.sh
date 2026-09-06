#!/usr/bin/env bash
# Portable CLI runner. Missing WQO installs into the current project's .wqo/venv.
set -euo pipefail
umask 077
compatible() {
  local version
  version="$("$1" --version 2>/dev/null)" || return 1
  printf '%s\n' "$version" | awk '
    /^wqo [0-9]+\.[0-9]+\.[0-9]+$/ {
      split($2,v,"."); if (v[1]>0 || v[2]>=1) ok=1
    } END {exit !ok}'
}
if command -v wqo >/dev/null 2>&1 && compatible "$(command -v wqo)"; then
  exec wqo "$@"
fi
project="${WQO_PROJECT_DIR:-$PWD}"
if [[ ! -d "$project" ]]; then
  echo "WQO_PROJECT_DIR must name an existing project directory." >&2
  exit 1
fi
project="$(cd "$project" && pwd -P)"
venv="$project/.wqo/venv"
if [[ -x "$venv/bin/wqo" ]] && compatible "$venv/bin/wqo"; then
  exec "$venv/bin/wqo" "$@"
fi
mkdir -p "$project/.wqo"
# Fail rather than run two concurrent installers against the same environment.
if ! mkdir "$project/.wqo/install.lock" 2>/dev/null; then
  echo "WQO setup is already running, or was interrupted. Check it before removing .wqo/install.lock." >&2
  exit 1
fi
trap 'rmdir "$project/.wqo/install.lock"' EXIT
if command -v uv >/dev/null 2>&1; then
  uv venv --python 3.12 --allow-existing "$venv" >&2
  uv pip install --python "$venv/bin/python" --default-index https://pypi.org/simple 'wqo==0.1.0' >&2
else
  python_bin=""
  for candidate in python3.14 python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3,12))' 2>/dev/null; then
      python_bin="$candidate"; break
    fi
  done
  if [[ -z "$python_bin" ]]; then
    echo "WQO requires uv or Python 3.12+. Install uv from https://docs.astral.sh/uv/getting-started/installation/ and retry." >&2
    exit 1
  fi
  "$python_bin" -m venv "$venv" >&2
  "$venv/bin/python" -m pip install --index-url https://pypi.org/simple 'wqo==0.1.0' >&2
fi
if ! compatible "$venv/bin/wqo"; then
  echo "WQO installation did not provide a compatible CLI; command was not run." >&2
  exit 1
fi
rmdir "$project/.wqo/install.lock"
trap - EXIT
exec "$venv/bin/wqo" "$@"
