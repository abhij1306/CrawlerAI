@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PYTHONDONTWRITEBYTECODE=1"
set "DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/crawlerai"
set "REDIS_URL=redis://localhost:6379/1"
set "REDIS_STATE_ENABLED=true"
set "CELERY_DISPATCH_ENABLED=true"
set "CRAWLERAI_WORKER_COUNT=2"
if exist "%ROOT%.env" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%ROOT%.env") do (
        if /I "%%A"=="DATABASE_URL" set "DATABASE_URL=%%~B"
        if /I "%%A"=="REDIS_URL" set "REDIS_URL=%%~B"
        if /I "%%A"=="REDIS_STATE_ENABLED" set "REDIS_STATE_ENABLED=%%~B"
        if /I "%%A"=="CELERY_DISPATCH_ENABLED" set "CELERY_DISPATCH_ENABLED=%%~B"
        if /I "%%A"=="CRAWLERAI_WORKER_COUNT" set "CRAWLERAI_WORKER_COUNT=%%~B"
    )
)
call :normalize_worker_count

if not exist "%ROOT%backend\.venv\Scripts\python.exe" (
    echo [ERROR] Backend environment missing. Run: cd backend ^&^& uv sync --frozen --extra dev
    exit /b 1
)
where vp >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Vite+ is missing. Install it, then run: cd frontend ^&^& vp install
    exit /b 1
)

echo [CrawlerAI] Stopping existing processes...
call :kill_window "CrawlerAI Backend"
call :kill_window "CrawlerAI Frontend"
call :kill_celery_workers

REM Kill individually-named worker windows; wildcard does not work with "WINDOWTITLE eq"
for /L %%I in (1,1,%CRAWLERAI_WORKER_COUNT%) do (
    taskkill /F /T /FI "WINDOWTITLE eq CrawlerAI Worker %%I" >nul 2>&1
)

call :kill_port 8001
call :kill_port 3001

if not exist "%ROOT%backend\artifacts" mkdir "%ROOT%backend\artifacts"

echo [CrawlerAI] REDIS_STATE_ENABLED=%REDIS_STATE_ENABLED%
echo [CrawlerAI] CELERY_DISPATCH_ENABLED=%CELERY_DISPATCH_ENABLED%
echo [CrawlerAI] CRAWLERAI_WORKER_COUNT=%CRAWLERAI_WORKER_COUNT%

set "REDIS_REQUIRED=false"
if /I "%REDIS_STATE_ENABLED%"=="true" set "REDIS_REQUIRED=true"
if /I "%CELERY_DISPATCH_ENABLED%"=="true" set "REDIS_REQUIRED=true"

if /I "%REDIS_REQUIRED%"=="true" (
    echo [CrawlerAI] Checking Redis at %REDIS_URL%...
    call :check_redis "%REDIS_URL%"
    if errorlevel 1 (
        echo [CrawlerAI] Redis unavailable. Starting local Docker service...
        docker compose up -d redis
        if errorlevel 1 exit /b 1
        call :wait_for_url "%REDIS_URL%" 6379
        if errorlevel 1 (
            echo [ERROR] Redis did not become ready at %REDIS_URL%.
            exit /b 1
        )
    )
    echo [CrawlerAI] Redis OK.
) else (
    echo [CrawlerAI] Redis/Celery disabled by .env. Using local in-process runner.
)

echo [CrawlerAI] Checking PostgreSQL...
call :check_database "%DATABASE_URL%"
if errorlevel 1 (
    echo [CrawlerAI] PostgreSQL unavailable. Starting local Docker service...
    docker compose up -d db
    if errorlevel 1 exit /b 1
    call :wait_for_url "%DATABASE_URL%" 5432
    if errorlevel 1 (
        echo [ERROR] PostgreSQL did not become ready.
        exit /b 1
    )
)

echo [CrawlerAI] Applying database migrations...
pushd "%ROOT%backend"
.venv\Scripts\python.exe init_db.py
if errorlevel 1 (
    popd
    echo [ERROR] Database migration failed.
    exit /b 1
)
popd

REM --- Backend -------------------------------------------------------
echo [CrawlerAI] Starting backend...
start "CrawlerAI Backend" /MIN /D "%ROOT%backend" cmd /k .venv\Scripts\python.exe run_dev_server.py

REM --- Frontend ------------------------------------------------------
echo [CrawlerAI] Starting frontend...
start "CrawlerAI Frontend" /MIN /D "%ROOT%frontend" cmd /k vp dev

REM --- Celery workers ------------------------------------------------
if /I "%CELERY_DISPATCH_ENABLED%"=="true" (
    echo [CrawlerAI] Starting %CRAWLERAI_WORKER_COUNT% Celery workers...
    for /L %%I in (1,1,%CRAWLERAI_WORKER_COUNT%) do (
        echo [CrawlerAI] Starting worker %%I...
        start "CrawlerAI Worker %%I" /MIN /D "%ROOT%backend" cmd /k "set PYTHONPATH=.&& .venv\Scripts\python.exe -m celery -A app.core.celery_app.celery_app worker --loglevel=INFO --pool=solo --concurrency=1 --hostname=crawlerai-worker-%%I@%COMPUTERNAME% --logfile=artifacts\celery-worker-%%I.log"
    )
) else (
    echo [CrawlerAI] Celery workers disabled.
)

echo [CrawlerAI] All processes started.
echo [CrawlerAI] Backend: http://127.0.0.1:8001
echo [CrawlerAI] Frontend: http://127.0.0.1:3001
echo [CrawlerAI] Worker logs: %ROOT%backend\artifacts\celery-worker-^<N^>.log
endlocal
goto :eof

REM ------------------------------------------------------------------
:check_redis
"%ROOT%backend\.venv\Scripts\python.exe" -c "import redis; client=redis.Redis.from_url('%~1', socket_connect_timeout=2, socket_timeout=2); raise SystemExit(0 if client.ping() else 1)" >nul 2>&1
exit /b %errorlevel%

:check_database
"%ROOT%backend\.venv\Scripts\python.exe" -c "import socket, urllib.parse; u=urllib.parse.urlparse('%~1'); s=socket.create_connection((u.hostname, u.port or 5432), timeout=2); s.close()" >nul 2>&1
exit /b %errorlevel%

:wait_for_url
for /L %%I in (1,1,20) do (
    "%ROOT%backend\.venv\Scripts\python.exe" -c "import socket, urllib.parse; u=urllib.parse.urlparse('%~1'); s=socket.create_connection((u.hostname, u.port or %~2), timeout=2); s.close()" >nul 2>&1
    if not errorlevel 1 exit /b 0
    timeout /t 1 /nobreak >nul
)
exit /b 1

:kill_window
taskkill /F /T /FI "WINDOWTITLE eq %~1" >nul 2>&1
exit /b 0

:kill_port
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$port = %~1; Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { $p = Get-Process -Id $_ -ErrorAction SilentlyContinue; if ($p -and $p.ProcessName -notmatch 'docker|wsl|vpnkit') { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }" >nul 2>&1
exit /b 0

:kill_celery_workers
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*--hostname=crawlerai-worker-*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
exit /b 0

:normalize_worker_count
if not defined CRAWLERAI_WORKER_COUNT set "CRAWLERAI_WORKER_COUNT=2"
set "CRAWLERAI_WORKER_COUNT_HAS_NONDIGIT="
for /f "delims=0123456789" %%A in ("%CRAWLERAI_WORKER_COUNT%") do set "CRAWLERAI_WORKER_COUNT_HAS_NONDIGIT=1"
if defined CRAWLERAI_WORKER_COUNT_HAS_NONDIGIT set "CRAWLERAI_WORKER_COUNT=2"
if "%CRAWLERAI_WORKER_COUNT%"=="0" set "CRAWLERAI_WORKER_COUNT=2"
exit /b 0
