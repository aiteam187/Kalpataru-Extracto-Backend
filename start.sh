#!/bin/bash
# ============================================================
# Extracto Backend — Ubuntu Startup Script
# Run: bash start.sh
# ============================================================

set -e  # Exit on any error

VENV_DIR="venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "❌ Error: Virtual environment '$VENV_DIR' not found."
    echo "Please run the setup script first:"
    echo "   bash setup.sh"
    exit 1
fi

echo "→ Activating virtual environment..."
source "$VENV_DIR/bin/activate"

echo "→ Starting Extracto backend server on http://0.0.0.0:8001 ..."
# We use python -m uvicorn app:app to ensure it runs within the virtualenv context
python -m uvicorn app:app --host 0.0.0.0 --port 8001 --reload
