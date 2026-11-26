@echo off
setlocal
rem Aurora - local offline media center shell
cd /d "%~dp0"

rem ---- find a usable Python (3.11+), including the py launcher ----
set "PY="
python -c "import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
    py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul && set "PY=py -3"
)

if not defined PY (
    echo Python 3.11+ was not found on this PC.
    choice /C YN /M "Install Python now"
    if errorlevel 2 goto :declined
    goto :install
)

rem ---- dependencies ----
%PY% -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    %PY% -m pip install -r requirements.txt
)

%PY% main.py %*
exit /b %errorlevel%

:install
where winget >nul 2>nul
if errorlevel 1 goto :no_winget
echo Installing Python via winget...
winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :no_winget
echo.
echo Python was installed. Close this window and run run.bat again.
pause
exit /b 0

:no_winget
echo Opening the official Python download page...
start "" "https://www.python.org/downloads/windows/"
echo Install Python 3.11+ ^(tick "Add python.exe to PATH"^), then run run.bat again.
pause
exit /b 0

:declined
echo Python 3.11+ is required to run Aurora. Exiting.
pause
exit /b 1
