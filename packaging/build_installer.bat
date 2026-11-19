@echo off
rem Build KHRAZ.exe (PyInstaller) and the installer (Inno Setup 6). ASCII + CRLF on purpose.
rem Requirements: Python 3.11+ in PATH; Inno Setup 6 (https://jrsoftware.org/isinfo.php) for the installer step.
cd /d "%~dp0"
if not exist ..\.venv (
  echo Run ..\setup.bat first.
  pause
  exit /b 1
)
call ..\.venv\Scripts\activate.bat
pip install "pyinstaller>=6.10" >nul
echo [1/2] PyInstaller: building dist\KHRAZ ...
pyinstaller khraz.spec --noconfirm --clean --distpath ..\dist --workpath ..\build
if errorlevel 1 (
  echo PyInstaller failed - see messages above.
  pause
  exit /b 1
)
echo [2/2] Inno Setup: building installer ...
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo Inno Setup 6 not found. The program is ready in ..\dist\KHRAZ\KHRAZ.exe
  echo Install Inno Setup 6 and run this file again to get KHRAZ-Setup.exe
  pause
  exit /b 0
)
%ISCC% installer.iss
echo.
echo Done: ..\dist\KHRAZ-Setup-2.0.0.exe
pause
