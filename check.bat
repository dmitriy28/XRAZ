@echo off
rem Check Ollama and models. ASCII + CRLF on purpose.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set PYTHONIOENCODING=utf-8
python startup.py
pause
