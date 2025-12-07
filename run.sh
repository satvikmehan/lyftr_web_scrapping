#!/usr/bin/env bash
set -e

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi

# Activate venv
# Linux / macOS
source venv/bin/activate || . venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Start the server on port 8000
python -m uvicorn main:app --host 0.0.0.0 --port 8000
