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
REQ_FILE="requirements.txt"
if [ -f requirements.lock.txt ]; then
  REQ_FILE="requirements.lock.txt"
  echo "=== pip install ($REQ_FILE) ==="
else
  echo "=== pip install ($REQ_FILE; для pin-версий добавьте requirements.lock.txt) ==="
fi
./.venv/bin/pip install -r "$REQ_FILE" -q

# HTTP API заявок: nginx location /fnr-api/ → 127.0.0.1:8765 (на canwant.ru уже настроено).
echo "=== статика Flex-n-roll → /var/www/canwant/flex-n-roll (canwant.ru/flex-n-roll/) ==="
FNR_WWW="/var/www/canwant/flex-n-roll"
sudo mkdir -p "$FNR_WWW"
sudo cp "$SCRIPT_DIR/flexn.html" "$FNR_WWW/index.html"
sudo cp -r "$SCRIPT_DIR/assets" "$FNR_WWW/"
sudo cp "$SCRIPT_DIR/privacy.html" "$FNR_WWW/privacy.html" 2>/dev/null || true
sudo cp "$SCRIPT_DIR/logo.svg" "$FNR_WWW/" 2>/dev/null || true
sudo rm -rf "$FNR_WWW/admin"
sudo cp -r "$SCRIPT_DIR/admin" "$FNR_WWW/"

GIT_SHORT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
if sudo test -f "$FNR_WWW/admin/index.html"; then
  sudo sed -i "s/DEPLOY_REV/${GIT_SHORT}/g" "$FNR_WWW/admin/index.html"
  echo "=== admin/index.html: fnr-deploy-rev = $GIT_SHORT (проверьте в браузере: view-source или DevTools → meta fnr-deploy-rev) ==="
else
  echo "=== ВНИМАНИЕ: нет $FNR_WWW/admin/index.html после копирования ===" >&2
fi

sudo chown -R www-data:www-data "$FNR_WWW"

echo "=== restart ==="
exec "$SCRIPT_DIR/restart.sh"
