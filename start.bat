@echo off
cd /d %~dp0
if not exist .venv ( python -m venv .venv )
call .venv\Scripts\activate
pip install -q -r requirements.txt
REM Change ici la commande de ton IA (le prompt arrive sur stdin) :
set AI_CMD=ollama run llama3.2
python server.py
pause
