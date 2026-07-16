#!/bin/bash
# ============================================================
# Extracto Backend — Ubuntu Setup Script
# Run once: bash setup.sh
# ============================================================

set -e  # Exit on any error

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Extracto Backend — Ubuntu Setup        ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. System packages ──────────────────────────────────────
echo "→ Updating system packages..."
sudo apt-get update -qq

echo "→ Installing Python 3, pip, and venv..."
sudo apt-get install -y python3 python3-pip python3-venv python3-dev

# ── 2. Virtual environment ───────────────────────────────────
VENV_DIR="venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "→ Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "→ Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# ── 3. Python dependencies ───────────────────────────────────
echo "→ Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# ── 4. .env file ─────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "→ Creating .env from .env.example..."
    cp .env.example .env
    echo ""
    echo "  ⚠️  Please edit .env and fill in your API keys before starting!"
    echo "      nano .env"
    echo ""
else
    echo "→ .env file found ✓"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the server:"
echo "   bash start.sh"
echo ""
