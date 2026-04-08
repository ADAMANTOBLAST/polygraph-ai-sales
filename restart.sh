#!/bin/bash
# Перезапуск PolygraphAiSales (python -m app.main) — только процессы с cwd == эта папка.
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

echo "=== остановка старых процессов (bot.py или -m app.main) ==="
for pid in $(pgrep -f "$BOT_DIR/.venv/bin/python" 2>/dev/null || true); do
  [ ! -d "/proc/$pid" ] && continue
  cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
  [ "$cwd" != "$BOT_DIR" ] && continue
  cmd=$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)
  case "$cmd" in
    *bot.py*|*-m\ app.main*) kill "$pid" 2>/dev/null || true ;;
  esac
done
sleep 2

LOG="$BOT_DIR/bot.log"
echo "=== запуск ==="
nohup "$PYTHON" -m app.main >>"$LOG" 2>&1 &
echo "PID $!. Лог: $LOG"
sleep 1
tail -5 "$LOG" 2>/dev/null || true
