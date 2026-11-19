@echo off
rem KHRAZ start. ASCII + CRLF on purpose.
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo Run setup.bat first.
  pause
  exit /b 1
)
rem If Ollama does not answer, try to start the Windows version (for Ollama in WSL run "ollama serve" there).
powershell -NoProfile -Command "try { Invoke-RestMethod http://localhost:11434/api/version -TimeoutSec 2 | Out-Null } catch { if (Get-Command ollama -ErrorAction SilentlyContinue) { Start-Process ollama -ArgumentList serve -WindowStyle Hidden } }"
start "" .venv\Scripts\pythonw.exe main.py
