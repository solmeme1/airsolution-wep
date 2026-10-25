#!/bin/bash
cd "$(dirname "$0")/collector"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  .venv/bin/python -m playwright install chromium
fi
[ -f .env ] || cp .env.example .env
.venv/bin/python collect.py --serve "$@"
