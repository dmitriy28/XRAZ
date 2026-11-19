#!/usr/bin/env bash
# Запуск ХРАЗа внутри WSL Ubuntu (окно через WSLg). Управление окнами Windows отсюда недоступно —
# для полного управления ПК запускайте run.bat в Windows; Ollama при этом может оставаться в WSL.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv-wsl ]; then
  python3 -m venv .venv-wsl
  .venv-wsl/bin/pip install -r requirements-wsl.txt
fi
# Ollama: в этой же WSL или в Windows (адрес хоста подберёт проверка при запуске)
curl -s --max-time 2 http://localhost:11434/api/version >/dev/null || (command -v ollama >/dev/null && (ollama serve >/dev/null 2>&1 &) && sleep 2) || true
.venv-wsl/bin/python startup.py || true
exec .venv-wsl/bin/python main.py "$@"
