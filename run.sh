#!/usr/bin/env bash
# Запуск MediaGrab на Linux/macOS.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Создаю виртуальное окружение…"
  python3 -m venv .venv
fi

echo "Устанавливаю зависимости…"
./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo
  echo "Создан .env. Впишите BOT_TOKEN от @BotFather и запустите снова:"
  echo "  nano .env"
  echo "  ./run.sh"
  exit 1
fi

./.venv/bin/python -m mediagrab --check
./.venv/bin/python -m mediagrab
