#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

has_data_dir_arg=0
for arg in "$@"; do
    case "$arg" in
        --data-dir|--data-dir=*)
            has_data_dir_arg=1
            ;;
    esac
done

if [ "$has_data_dir_arg" -eq 0 ] && [ -z "${BORDER_CONTROL_DATA_DIR:-}" ]; then
    if [ -d /mnt/storage ]; then
        DATA_DIR=/mnt/storage/border-control
    elif [ -d /media ]; then
        DATA_DIR=/media/border-control
    else
        DATA_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/border-control"
    fi
    mkdir -p "$DATA_DIR/data"
    set -- --data-dir "$DATA_DIR" "$@"
fi

if [ -x "$APP_ROOT/.venv/bin/python" ]; then
    PYTHON_BIN="$APP_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "Python interpreter was not found (expected python3 or python)." >&2
    exit 1
fi

exec "$PYTHON_BIN" "$APP_ROOT/main.py" "$@"
