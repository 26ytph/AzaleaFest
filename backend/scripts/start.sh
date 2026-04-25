#!/usr/bin/env bash
# Backend 容器啟動腳本（docker-compose backend service 的 command）.
#
# 流程:
#   1. alembic upgrade head — 套 migration（含 0002 雙 embedding schema）
#   2. bootstrap_attractions.py — 若 attractions 空，從 HF dataset 拉預算好的 dump
#   3. exec uvicorn — 啟 FastAPI
#
# 設計見 M1.md §15。
set -euo pipefail

cd /app

# Hot-patch: 舊 image 裝的是 line-bot-sdk 3.14.0（該 release 有 syntax bug），
# requirements.txt 已 pin 3.14.5，但 image 還沒 rebuild。容器啟動時補裝。
# rebuild image 後可移除這段。
if ! python -c "import importlib.metadata; v=importlib.metadata.version('line-bot-sdk'); assert v == '3.14.5', v" 2>/dev/null; then
  echo "[start] hot-patching line-bot-sdk -> 3.14.5"
  pip install --quiet --upgrade 'line-bot-sdk==3.14.5'
fi

echo "[start] alembic upgrade head"
alembic upgrade head

echo "[start] bootstrap attractions (auto-skip if populated)"
python scripts/bootstrap_attractions.py

echo "[start] uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
