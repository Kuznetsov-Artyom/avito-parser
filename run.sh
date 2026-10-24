#!/usr/bin/env bash
# Запуск сайта-парсера Avito: http://127.0.0.1:8000
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
exec uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
