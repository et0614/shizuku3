#!/bin/bash
# Opens a shell with the virtual environment activated,
# ready to run the examples (python examples/01_onoff_control.py).
# Run setup.command once before using this.
cd "$(dirname "$0")"
if [ ! -f .venv/bin/activate ]; then
    echo "Virtual environment not found. Run setup.command first."
    read -p "Press Enter to close..."
    exit 1
fi
exec bash --rcfile .venv/bin/activate
