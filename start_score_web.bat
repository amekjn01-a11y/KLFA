@echo off
cd /d "%~dp0"
python -m uvicorn score_web_app:app --host 0.0.0.0 --port 8000
pause
