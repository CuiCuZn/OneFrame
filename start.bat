@echo off
chcp 65001 >nul
setlocal EnableExtensions
title OneFrame Launcher
cd /d "%~dp0"

echo.
echo   OneFrame - local AI image and video studio
echo   ------------------------------------------------
echo.

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

if not defined PY (
  where py >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo [x] Python was not found.
  echo     Install Python 3.11 or newer and tick "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 goto fail
  echo [2/3] Installing backend dependencies...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r backend\requirements.txt
  if errorlevel 1 goto fail
)

if not exist "frontend\dist\index.html" (
  echo [3/3] Building frontend...
  pushd frontend
  call npm install --no-fund --no-audit
  if errorlevel 1 (
    popd
    goto fail
  )
  call npm run build
  if errorlevel 1 (
    popd
    goto fail
  )
  popd
)

echo Starting OneFrame at http://127.0.0.1:8787
echo Keep this window open. Press Ctrl+C to stop.
echo.

".venv\Scripts\python.exe" backend\run.py
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
  echo.
  echo [x] OneFrame exited with code %CODE%.
  echo     See the messages above.
  echo.
  pause
)
exit /b %CODE%

:fail
echo.
echo [x] Setup failed. See the messages above.
pause
exit /b 1
