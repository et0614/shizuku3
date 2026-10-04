#!/bin/bash
# One-time setup: creates the Python virtual environment (.venv) and
# installs the Shizuku3 client with all extras (web GUI + RL).
# Just double-click this file in Finder. Requires Python 3.10+
# (install it from https://www.python.org/).
cd "$(dirname "$0")"

# Files downloaded from the internet are quarantined by macOS (Gatekeeper);
# clear the flag on the whole folder so Shizuku3 and the other .command
# files open without further warnings.
xattr -dr com.apple.quarantine . 2>/dev/null
chmod +x Shizuku3 *.command 2>/dev/null

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python not found. Install Python 3.10+ from https://www.python.org/"
    read -p "Press Enter to close..."
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "Creating the virtual environment..."
    python3 -m venv .venv || { read -p "Press Enter to close..."; exit 1; }
fi

source .venv/bin/activate
echo "Installing the Python packages (this downloads PyTorch - be patient)..."
python -m pip install -e "client[all]" || { read -p "Press Enter to close..."; exit 1; }

echo
echo "============================================================"
echo " Setup complete. This window is ready to use."
echo " Next: double-click Shizuku3, then double-click start_gui.command,"
echo " or run the examples right here:"
echo "     python examples/01_onoff_control.py"
echo "============================================================"
exec bash -i
