#!/bin/bash
# Перезапуск бота PolygraphAiSales — только процессы с cwd == эта папка и bot.py.
set -euo pipefail
BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BOT_DIR"

PYTHON=""
if [ -x "$BOT_DIR/.venv/bin/python" ]; then
  PYTHON="$BOT_DIR/.venv/bin/python"
elif [ -x "$BOT_DIR/venv/bin/python" ]; then
  PYTHON="$BOT_DIR/venv/bin/python"
else
  echo "Нет .venv — создайте: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "=== остановка старых процессов ($BOT_DIR/bot.py) ==="
for pid in $(pgrep -f "$BOT_DIR/bot.py" 2>/dev/null || true); do
  [ ! -d "/proc/$pid" ] && continue
  cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
  [ "$cwd" = "$BOT_DIR" ] && kill "$pid" 2>/dev/null || true
done
sleep 2

LOG="$BOT_DIR/bot.log"
echo "=== запуск ==="
nohup "$PYTHON" "$BOT_DIR/bot.py" >>"$LOG" 2>&1 &
echo "PID $!. Лог: $LOG"
sleep 1
tail -5 "$LOG" 2>/dev/null || true
