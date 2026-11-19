#!/bin/sh
# Launch the complete console on this Mac and open it in the default browser.
set -eu
project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir/desktop"
if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    interpreter="$VIRTUAL_ENV/bin/python"
elif [ -x .venv/bin/python ]; then
    interpreter=.venv/bin/python
elif [ -x ../.venv/bin/python ]; then
    interpreter=../.venv/bin/python
else
    command -v python3 >/dev/null 2>&1 || { echo 'Install Python 3.10 or newer and reopen this launcher.'; exit 1; }
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo 'Python 3.10 or newer is required.'; exit 1; }
    python3 -m venv .venv
    interpreter=.venv/bin/python
fi
if ! "$interpreter" main.py --check >/dev/null 2>&1; then
    "$interpreter" -m pip install -r requirements.txt
    "$interpreter" main.py --check
fi
exec "$interpreter" browser_console.py
