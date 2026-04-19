#!/usr/bin/env bash
# Run this from your local machine (residential IP required for Hyperliquid API).
# Usage: ./run_briefing.sh
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

echo "==> Pulling latest..."
git pull origin main

echo "==> Installing dependencies..."
pip3 install requests --quiet

echo "==> Scanning whales (top 50 + rekt 50)..."
python3 scripts/whale_scanner.py both 50 > /tmp/whale_data.json

echo "==> Generating briefing..."
python3 scripts/generate_briefing.py

echo "==> Committing and pushing..."
git add briefings/
git commit -m "Daily whale briefing $(date +%Y-%m-%d)"
git push origin main

echo "==> Done."
