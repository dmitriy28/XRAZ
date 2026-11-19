@echo off
rem Start KHRAZ as administrator (to control windows of elevated programs). ASCII + CRLF on purpose.
cd /d "%~dp0"
powershell -NoProfile -Command "Start-Process -FilePath '%~dp0.venv\Scripts\pythonw.exe' -ArgumentList '\"%~dp0main.py\"' -WorkingDirectory '%~dp0' -Verb RunAs"
