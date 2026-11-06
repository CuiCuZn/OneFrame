@echo off
setlocal EnableExtensions
title OneFrame Stop
cd /d "%~dp0"

if not exist "data\oneframe.pid" goto byport

set /p PID=<"data\oneframe.pid"
if "%PID%"=="" goto stale

powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + %PID%) -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -like '*backend\run.py*') { Stop-Process -Id %PID% -Force; exit 0 } else { exit 1 }"
if not errorlevel 1 (
  echo Stopped OneFrame, PID %PID%.
  del "data\oneframe.pid" >nul 2>nul
  ping -n 2 127.0.0.1 >nul
  exit /b 0
)
echo PID %PID% is not the OneFrame server. Removing stale pid file.
del "data\oneframe.pid" >nul 2>nul

:byport
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $c) { exit 2 }; $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $c.OwningProcess) -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -like '*backend\run.py*') { Stop-Process -Id $c.OwningProcess -Force; exit 0 }; exit 1"
if errorlevel 2 (
  echo OneFrame is not running.
  ping -n 2 127.0.0.1 >nul
  exit /b 0
)
if errorlevel 1 (
  echo Port 8787 is used by another program. Nothing was stopped.
  pause
  exit /b 1
)
echo Stopped OneFrame on port 8787.
ping -n 2 127.0.0.1 >nul
exit /b 0

:stale
del "data\oneframe.pid" >nul 2>nul
echo Stale pid file removed.
ping -n 2 127.0.0.1 >nul
exit /b 0
