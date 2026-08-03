#!/usr/bin/env bash
# 一键启动：FastAPI 后端 :8899 + Vite 前端 :5173
set -e
cd "$(dirname "$0")"

source .venv/bin/activate
python3 apps/server/main.py &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT

cd apps/web && pnpm dev
