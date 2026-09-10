#!/usr/bin/env bash
set -euo pipefail
plugin_root="${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}}"
bundled_runtime="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies"
if [ -d "$bundled_runtime/bin/fallback" ]; then
  export PATH="$bundled_runtime/bin/fallback:$PATH"
fi
for candidate in "${AUTORESEARCH_PYTHON:-python3}" "$bundled_runtime/python/bin/python3" python3.12 python3.11; do
  if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
    exec "$candidate" "$plugin_root/scripts/native_hooks.py"
  fi
done
printf '%s\n' '{"systemMessage":"Autoresearch hooks need Python 3.9+. Set AUTORESEARCH_PYTHON to a working interpreter."}'
