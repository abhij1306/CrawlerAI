@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "REDIS_URL=redis://localhost:6380/0"
set "REDIS_STATE_ENABLED=false"
set "CELERY_DISPATCH_ENABLED=true"
set "INVORO_WORKER_COUNT=2"
if exist "%ROOT%.env" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%ROOT%.env") do (
        if /I "%%A"=="REDIS_URL" set "REDIS_URL=%%~B"
        if /I "%%A"=="REDIS_STATE_ENABLED" set "REDIS_STATE_ENABLED=%%~B"
        if /I "%%A"=="CELERY_DISPATCH_ENABLED" set "CELERY_DISPATCH_ENABLED=%%~B"
        if /I "%%A"=="INVORO_WORKER_COUNT" set "INVORO_WORKER_COUNT=%%~B"
    )
)
call :normalize_worker_count

echo [Invoro] Stopping existing processes...
call :kill_window "Invoro Backend"
call :kill_window "Invoro Frontend"
call :kill_celery_workers
call :kill_browser_runtimes

REM Kill individually-named worker windows; wildcard does not work with "WINDOWTITLE eq"
for /L %%I in (1,1,%INVORO_WORKER_COUNT%) do (
    taskkill /F /T /FI "WINDOWTITLE eq Invoro Worker %%I" >nul 2>&1
)

call :kill_port 8000
call :kill_port 3000

if not exist "%ROOT%backend\artifacts" mkdir "%ROOT%backend\artifacts"

echo [Invoro] REDIS_STATE_ENABLED=%REDIS_STATE_ENABLED%
echo [Invoro] CELERY_DISPATCH_ENABLED=%CELERY_DISPATCH_ENABLED%
echo [Invoro] INVORO_WORKER_COUNT=%INVORO_WORKER_COUNT%

set "REDIS_REQUIRED=false"
if /I "%REDIS_STATE_ENABLED%"=="true" set "REDIS_REQUIRED=true"
if /I "%CELERY_DISPATCH_ENABLED%"=="true" set "REDIS_REQUIRED=true"

if /I "%REDIS_REQUIRED%"=="true" (
    echo [Invoro] Checking Redis at %REDIS_URL%...
    call :check_redis "%REDIS_URL%"
    if errorlevel 1 (
        echo.
        echo  [ERROR] Redis is not reachable at %REDIS_URL%.
        echo  Start Redis before enabling REDIS_STATE_ENABLED or CELERY_DISPATCH_ENABLED.
        echo.
        pause
        exit /b 1
    )
    echo [Invoro] Redis OK.
) else (
    echo [Invoro] Redis/Celery disabled by .env. Using local in-process runner.
)

REM --- Backend -------------------------------------------------------
echo [Invoro] Starting backend...
start "Invoro Backend" /MIN /D "%ROOT%backend" cmd /k .venv\Scripts\python.exe run_dev_server.py

REM --- Frontend ------------------------------------------------------
echo [Invoro] Starting frontend...
start "Invoro Frontend" /MIN /D "%ROOT%frontend" cmd /k npm.cmd run dev

REM --- Celery workers ------------------------------------------------
if /I "%CELERY_DISPATCH_ENABLED%"=="true" (
    echo [Invoro] Starting %INVORO_WORKER_COUNT% Celery workers...
    for /L %%I in (1,1,%INVORO_WORKER_COUNT%) do (
        echo [Invoro] Starting worker %%I...
        start "Invoro Worker %%I" /B /D "%ROOT%backend" cmd /k "set PYTHONPATH=.&& .venv\Scripts\python.exe -m celery -A app.core.celery_app.celery_app worker --loglevel=INFO --pool=solo --concurrency=1 --hostname=invoro-worker-%%I@%COMPUTERNAME% --logfile=artifacts\celery-worker-%%I.log"
    )
) else (
    echo [Invoro] Celery workers disabled.
)

echo [Invoro] All processes started.
echo [Invoro] Worker logs: %ROOT%backend\artifacts\celery-worker-^<N^>.log
endlocal
goto :eof

REM ------------------------------------------------------------------
:check_redis
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { $u = [Uri]'%~1'; $port = if ($u.Port -gt 0) { $u.Port } else { 6380 }; $c = New-Object System.Net.Sockets.TcpClient($u.Host, $port); $c.Close(); exit 0 } catch { exit 1 }"
exit /b %errorlevel%

:kill_window
taskkill /F /T /FI "WINDOWTITLE eq %~1" >nul 2>&1
exit /b 0

:kill_port
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$port = %~1; Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>&1
exit /b 0

:kill_celery_workers
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*app.core.celery_app.celery_app worker*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
exit /b 0

:kill_browser_runtimes
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(chrome|chromium|msedge)\.exe$' -and ($_.CommandLine -match '--remote-debugging-(pipe|port)' -or $_.CommandLine -match '(playwright|patchright)') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
exit /b 0

:normalize_worker_count
if not defined INVORO_WORKER_COUNT set "INVORO_WORKER_COUNT=2"
set "INVORO_WORKER_COUNT_HAS_NONDIGIT="
for /f "delims=0123456789" %%A in ("%INVORO_WORKER_COUNT%") do set "INVORO_WORKER_COUNT_HAS_NONDIGIT=1"
if defined INVORO_WORKER_COUNT_HAS_NONDIGIT set "INVORO_WORKER_COUNT=2"
if "%INVORO_WORKER_COUNT%"=="0" set "INVORO_WORKER_COUNT=2"
exit /b 0
