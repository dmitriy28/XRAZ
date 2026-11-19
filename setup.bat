@echo off
rem KHRAZ setup. This file is ASCII with CRLF line endings on purpose (cmd.exe breaks on UTF-8/LF .bat files).
cd /d "%~dp0"
echo [1/5] Python virtual environment...
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ not found. Install it from python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
echo [2/5] Python packages...
pip install -r requirements.txt
if errorlevel 1 (
  echo Package installation failed - see the messages above.
  pause
  exit /b 1
)
if not exist models mkdir models
echo [3/5] Vosk speech model (45 MB)...
if not exist models\vosk-model-small-ru-0.22 (
  powershell -NoProfile -Command "Invoke-WebRequest https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip -OutFile models\vosk.zip; Expand-Archive models\vosk.zip -DestinationPath models -Force; Remove-Item models\vosk.zip"
)
echo [4/5] Piper offline voice (60 MB)...
if not exist models\piper mkdir models\piper
if not exist models\piper\ru_RU-dmitri-medium.onnx (
  powershell -NoProfile -Command "$b='https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx'; Invoke-WebRequest $b -OutFile models\piper\ru_RU-dmitri-medium.onnx; Invoke-WebRequest ($b+'.json') -OutFile models\piper\ru_RU-dmitri-medium.onnx.json"
)
echo [5/5] Checking Ollama and models...
set PYTHONIOENCODING=utf-8
python startup.py
echo.
echo If models are missing, run the "ollama pull ..." commands shown above.
echo Ollama inside WSL: run "ollama serve" in Ubuntu, KHRAZ will use http://localhost:11434
echo Start KHRAZ: run.bat
pause
