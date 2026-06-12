#!/bin/bash
# ─────────────────────────────────────────────────────────────────
#  Expert Radiology – Signature Generator  |  Local startup script
# ─────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  ┌──────────────────────────────────────────────────────┐"
echo "  │   Expert Radiology — Signature Generator             │"
echo "  │   Local microservice · port 5050                     │"
echo "  └──────────────────────────────────────────────────────┘"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "  ❌  python3 not found. Please install Python 3.9+."
  exit 1
fi

# Install dependencies if needed
if ! python3 -c "import flask, PIL" &>/dev/null; then
  echo "  📦  Installing dependencies…"
  pip3 install -r requirements.txt --quiet
fi

echo "  ✅  Starting server at http://localhost:5050"
echo "  ℹ️   Press Ctrl+C to stop"
echo ""

python3 app.py
