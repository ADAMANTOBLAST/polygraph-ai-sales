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

# HTTP API заявок: nginx location /fnr-api/ → 127.0.0.1:8765 (на canwant.ru уже настроено).
echo "=== статика Flex-n-roll → /var/www/canwant/flex-n-roll (canwant.ru/flex-n-roll/) ==="
FNR_WWW="/var/www/canwant/flex-n-roll"
sudo mkdir -p "$FNR_WWW"
sudo cp "$SCRIPT_DIR/flexn.html" "$FNR_WWW/index.html"
sudo cp -r "$SCRIPT_DIR/assets" "$FNR_WWW/"
sudo cp "$SCRIPT_DIR/logo2.png" "$FNR_WWW/" 2>/dev/null || true
sudo rm -rf "$FNR_WWW/admin"
sudo cp -r "$SCRIPT_DIR/admin" "$FNR_WWW/"
sudo chown -R www-data:www-data "$FNR_WWW"

echo "=== restart ==="
exec "$SCRIPT_DIR/restart.sh"
