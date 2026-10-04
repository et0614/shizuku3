#!/bin/bash
# Starts the web GUI; a browser opens automatically.
# Start Shizuku3 first, and run setup.command once before using this.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "Virtual environment not found. Run setup.command first."
    read -p "Press Enter to close..."
    exit 1
fi
.venv/bin/python gui/server.py
read -p "Press Enter to close..."
