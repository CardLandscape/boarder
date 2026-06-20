# Handoff

## Current Status
- The application remains a Python `curses` terminal program.
- The codebase has been prepared for Linux live media by separating read-only assets from writable runtime state.
- Default behavior is unchanged for local development: running from the project directory still uses local files by default.

## Changes Completed
- Added runtime path configuration in `main.py`.
- Added `--data-dir` CLI support.
- Added `BORDER_CONTROL_DATA_DIR` environment variable support.
- Kept offline assets in `data/` next to the application.
- Redirected writable state to a configurable location:
  - `passenger_data.json`
  - `data/system_settings.json`
  - `data/error.log`
- Added Linux startup wrapper: `scripts/start_linux.sh`.
- Added systemd unit template: `scripts/border-control.service.example`.
- Added ISO build pipeline files under `iso/live-build/`.
- Added Windows entry script for ISO build via WSL: `scripts/build_iso.ps1`.
- Added Linux ISO build entry script: `scripts/build_iso_linux.sh`.
- Added GitHub Actions ISO build workflow: `.github/workflows/build-iso.yml`.
- Updated `requirements.txt` so `windows-curses` installs only on Windows.
- Updated `README.md` with Linux/read-only-media notes.

## Validated
- `py -m py_compile main.py`
- Import and runtime path checks using `py -c ...`
- Wrapper argument and data-dir fallback behavior reviewed in `scripts/start_linux.sh`.
- ISO build script flow reviewed for WSL live-build execution path.

## Important Runtime Behavior
- Read-only bundled assets stay under the project `data/` directory.
- Writable runtime files can be redirected with either:
  - `python main.py --data-dir /path/to/writable/location`
  - `BORDER_CONTROL_DATA_DIR=/path/to/writable/location`

## Recommended Next Steps
1. Build a minimal live Linux image instead of targeting DOS.
2. Wire `scripts/border-control.service.example` into the image at install time.
3. Optionally package the app with PyInstaller or Nuitka for easier deployment.
4. Consider separating business logic from the `curses` UI to make future ports easier.

## Move To Another Computer
1. Copy the whole project folder.
2. Install Python on the target machine.
3. Install dependencies with `pip install -r requirements.txt`.
4. Run `py main.py` on Windows or `python main.py` on Linux.
5. If running from read-only media, pass `--data-dir` to a writable path.

## Notes
- `git` was not available in the current shell, so no repository status snapshot was recorded.
- The current work is saved directly in the workspace files.
- Attempting `wsl --install -d Debian --no-launch` in this environment returned `Access is denied`, so final ISO generation is currently blocked by host permissions rather than project code.
- Running `scripts/build_iso.ps1` locally is also blocked by this machine's policy and WSL distro availability.