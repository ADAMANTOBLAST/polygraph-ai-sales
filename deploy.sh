#!/bin/bash
# Деплой production: подтянуть main с origin и перезапустить бота.
# Вызывается вручную на сервере или из GitHub Actions по SSH.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== git: fetch main ==="
git fetch origin main
git checkout main
git reset --hard origin/main

if [ ! -d ".venv" ]; then
  echo "=== python3 -m venv .venv ==="
  python3 -m venv .venv
fi
echo "=== pip install ==="
./.venv/bin/pip install -r requirements.txt -q

echo "=== restart ==="
exec "$SCRIPT_DIR/restart.sh"
