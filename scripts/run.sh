#!/usr/bin/env bash
# macOS / Linux: ./scripts/run.sh          (real OpenAI calls, key from .env)
#                ./scripts/run.sh --mock   (free, placeholder images)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/pip install -q -r requirements.txt
[ "${1:-}" = "--mock" ] && export MOCK=1
# --host 0.0.0.0 so a phone on the same Wi-Fi can open http://<this-computer's-IP>:8000
exec .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
