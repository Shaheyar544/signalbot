@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON=%CD%\.venv\Scripts\python.exe"
set "CONFIG=%CD%\config.yaml"

if not exist "%PYTHON%" (
  echo ERROR: Virtual environment not found.
  echo Run: python -m venv .venv
  echo Then: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
if not exist "%CONFIG%" (
  echo ERROR: config.yaml was not found in %CD%
  pause
  exit /b 1
)

set "ENGINE_ROOTS=0"
set "DASHBOARD_ROOTS=0"
for /f %%C in ('powershell -NoProfile -Command "$p=@(); foreach($x in Get-CimInstance Win32_Process){if($x.Name -eq 'python.exe' -and $x.CommandLine -match '-m app.main'){$p+=$x}}; $ids=@(); foreach($x in $p){$ids+=$x.ProcessId}; $count=0; foreach($x in $p){if($x.ParentProcessId -notin $ids){$count++}}; $count"') do set "ENGINE_ROOTS=%%C"
for /f %%C in ('powershell -NoProfile -Command "$p=@(); foreach($x in Get-CimInstance Win32_Process){if($x.Name -eq 'python.exe' -and $x.CommandLine -match '-m app.dashboard'){$p+=$x}}; $ids=@(); foreach($x in $p){$ids+=$x.ProcessId}; $count=0; foreach($x in $p){if($x.ParentProcessId -notin $ids){$count++}}; $count"') do set "DASHBOARD_ROOTS=%%C"

if %ENGINE_ROOTS% GTR 1 (
  echo ERROR: More than one Signalbot engine is already running.
  echo Close duplicate app.main processes before starting again.
  pause
  exit /b 1
)
if %DASHBOARD_ROOTS% GTR 1 (
  echo ERROR: More than one Signalbot dashboard is already running.
  echo Close duplicate app.dashboard processes before starting again.
  pause
  exit /b 1
)

if %ENGINE_ROOTS% EQU 0 (
  start "Signalbot Engine" /min "%PYTHON%" -m app.main --config config.yaml
  echo Signal engine started.
) else (
  echo Signal engine is already running.
)

if %DASHBOARD_ROOTS% EQU 0 (
  start "Signalbot Dashboard" /min "%PYTHON%" -m app.dashboard --config config.yaml --host 127.0.0.1 --port 8000
  echo Dashboard started.
) else (
  echo Dashboard is already running.
)

ping 127.0.0.1 -n 4 >nul
start "" "http://127.0.0.1:8000"
echo.
echo Signalbot is available at http://127.0.0.1:8000
