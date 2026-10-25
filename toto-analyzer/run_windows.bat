@echo off
chcp 65001 >nul
cd /d %~dp0collector
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
  .venv\Scripts\python -m playwright install chromium
)
if not exist .env copy .env.example .env >nul
.venv\Scripts\python collect.py --serve %*
pause
