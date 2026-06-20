# Border Control Passenger Entry and Exit System

A simple Python command-line interface for managing passenger entry and exit records.

## Features
- Register passenger entry
- Register passenger exit
- View current passengers
- View all historical logs
- Save and load data from `passenger_data.json`

## Run
1. Open the workspace in VS Code.
2. Create and activate a Python virtual environment if desired.
3. Install required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the application:
   ```bash
   py main.py
   ```
   If your environment provides `python`, you can also use:
   ```bash
   python main.py
   ```

## Linux and Read-Only Media
- The application now separates bundled assets from writable runtime state.
- Offline lookup files remain in `data/` next to the program.
- Passenger data, settings, and error logs can be redirected to a writable directory with `--data-dir` or `BORDER_CONTROL_DATA_DIR`.

### Quick Start Wrapper (Linux)
- Use `scripts/start_linux.sh` to auto-detect a writable location and launch the app.
- The wrapper checks locations in this order when no data path is provided:
   1. `/mnt/storage/border-control`
   2. `/media/border-control`
   3. `${XDG_STATE_HOME:-$HOME/.local/state}/border-control`
- It also respects any explicit `--data-dir` argument or `BORDER_CONTROL_DATA_DIR` environment variable.

Example:

```bash
chmod +x scripts/start_linux.sh
./scripts/start_linux.sh
```

Examples:

```bash
python main.py --data-dir /mnt/storage/border-control
```

```bash
export BORDER_CONTROL_DATA_DIR=/mnt/storage/border-control
python main.py
```

When running from a live CD/DVD or other read-only media, point the writable directory to a USB drive, writable partition, tmpfs, or network-mounted path.

## Bootable Linux Direction
For a bootable optical disc deployment, the practical target is a minimal Linux live system rather than DOS:

1. Build a live image with a console environment.
2. Bundle this project and its `data/` assets into the image.
3. Start the application automatically on tty login.
4. Pass `--data-dir` to a writable mount such as `/mnt/storage/border-control`.

For systemd-based images, you can start from `scripts/border-control.service.example`.

## Build A Bootable ISO (WSL)
The repository now includes an automated live-build pipeline that creates a VM-bootable ISO.

1. Install a WSL distro (Debian recommended):
   ```powershell
   wsl --install -d Debian
   ```
2. Open an elevated PowerShell in this project and run:
   ```powershell
   .\scripts\build_iso.ps1
   ```
3. Output ISO is written to `dist/` with a timestamped name.

The image auto-starts the border-control app on tty1 and stores runtime data under `/var/lib/border-control`.

### Build ISO In GitHub Actions
If local WSL setup is blocked by permissions, use the workflow at `.github/workflows/build-iso.yml`:

1. Push this repository to GitHub.
2. Run the **Build Bootable ISO** workflow from the Actions tab.
3. Download the `border-control-iso` artifact and attach it directly to your VM.

DOS is not a practical target for the current codebase because the program depends on Python, `curses`, UTF-8 terminal behavior, and modern filesystem semantics.

## Packaging for another computer
1. Compress the project folder into a ZIP archive, or use Git to push and clone it.
2. Include these files and folders:
   - `main.py`
   - `passenger_data.json`
   - `requirements.txt`
   - `README.md`
   - `data/`
   - `scripts/`
3. On the new computer, extract the archive and run the same install commands above.

## Continue in VS Code with Copilot AI
1. Open the project folder in VS Code.
2. Install the Python extension and the GitHub Copilot / Copilot Chat extension.
3. Open `main.py` and ask Copilot to help continue development.

## Notes
- The interface uses a full-screen TUI and is best viewed in a terminal of at least 80x24.
- The system supports:
  - Staff Card and Staff Passport documents
  - Document validity checks
  - Permit issuance, validity checks, and revocation
  - Entry registration using existing visa, issuing a new visa, or approving stay without visa
- Data is saved automatically to `passenger_data.json`.
