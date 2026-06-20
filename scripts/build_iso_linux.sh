#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
LIVE_ROOT="$APP_ROOT/iso/live-build"
INCLUDE_ROOT="$LIVE_ROOT/config/includes.chroot/opt/border-control"

echo "[1/5] Installing live-build dependencies"
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y live-build rsync xorriso
fi

echo "[2/5] Syncing app files into image"
rm -rf "$INCLUDE_ROOT"
mkdir -p "$INCLUDE_ROOT"
for item in main.py requirements.txt README.md passenger_data.json data scripts; do
    if [ -e "$APP_ROOT/$item" ]; then
        cp -a "$APP_ROOT/$item" "$INCLUDE_ROOT/"
    fi
done

echo "[3/5] Preparing live-build"
cd "$LIVE_ROOT"
chmod +x auto/config config/hooks/live/010-border-control.chroot

lb clean --purge
./auto/config

echo "[4/5] Building ISO"
lb build

echo "[5/5] Collecting artifact"
mkdir -p "$APP_ROOT/dist"
ISO_PATH="$LIVE_ROOT/live-image-amd64.hybrid.iso"
if [ ! -f "$ISO_PATH" ]; then
    echo "ISO not found: $ISO_PATH" >&2
    exit 1
fi
OUT="$APP_ROOT/dist/border-control-$(date +%Y%m%d-%H%M%S).iso"
cp "$ISO_PATH" "$OUT"
echo "ISO ready: $OUT"
