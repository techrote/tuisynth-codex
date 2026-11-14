#!/bin/sh
# TRIO's bootstrap owns dependency setup; this wrapper only selects Python.
set -eu
trio_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
if [ -n "${TRIO_PYTHON:-}" ]; then
    exec "$TRIO_PYTHON" -I "$trio_root/tools/launch.py" "$@"
fi
if command -v python3 >/dev/null 2>&1 && python3 -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    exec python3 -I "$trio_root/tools/launch.py" "$@"
fi
if command -v python >/dev/null 2>&1 && python -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    exec python -I "$trio_root/tools/launch.py" "$@"
fi
printf '%s\n' 'TRIO needs Python 3.11 or newer. Install Python or set TRIO_PYTHON to its executable.' >&2
exit 2
