@echo off
REM start-full-stack.bat — Idempotent one-click launcher for the full stack.
REM
REM Safe to run repeatedly:
REM   * keeps an existing .env (DB volumes keep their passwords);
REM   * repairs nginx, the CA bundle and the Keycloak client secret;
REM   * registers the reSpotIt MCP connection and starts a sync.
REM
REM Usage: start-full-stack.bat [bootstrap options]
REM   --no-sync      do not start a library sync
REM   --no-verify    skip the final checks
setlocal

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [error] Python 3 is required but was not found on PATH.
    exit /b 1
)
where docker >nul 2>&1
if errorlevel 1 (
    echo [error] Docker is required but was not found on PATH.
    exit /b 1
)

echo [..] Preparing full-stack files and settings...
python scripts\prepare_full_stack.py
if errorlevel 1 (
    echo [error] Preparation failed. Fix the message above and re-run.
    exit /b 1
)

REM Read the LAN origin that prepare just wrote, so every printed URL is
REM reachable from a phone or a second PC (never localhost).
for /f "tokens=2 delims==" %%a in ('findstr /b "PUBLIC_ORIGIN=" .env') do set "PUBLIC_ORIGIN=%%a"
for /f "tokens=2 delims==" %%a in ('findstr /b "LAN_IP=" .env') do set "LAN_IP=%%a"
if not defined PUBLIC_ORIGIN set "PUBLIC_ORIGIN=https://localhost"
if not defined LAN_IP set "LAN_IP=localhost"

echo [..] Starting containers...
docker compose -f docker-compose.yml -f docker-compose.full.yml up -d --build
if errorlevel 1 (
    echo [error] docker compose failed. Fix the message above and re-run.
    exit /b 1
)

echo [..] Bootstrapping services...
python scripts\bootstrap_full_stack.py %*
set "BOOTSTRAP_RC=%ERRORLEVEL%"
if not "%BOOTSTRAP_RC%"=="0" (
    echo [warn] Bootstrap reported a problem. Containers are running; see above.
)

echo.
if "%BOOTSTRAP_RC%"=="0" (
    echo [OK] Full stack started!
) else (
    echo [warn] Full stack started with warnings. See the bootstrap output above.
)
echo    reSpotIt frontend: http://%LAN_IP%:8888
echo    reSpotIt API:      https://%LAN_IP%:8000
echo    OpenWebUI:         %PUBLIC_ORIGIN%/
echo    Keycloak Admin:    %PUBLIC_ORIGIN%/authKeycloak/admin/
echo    MinIO Console:     http://%LAN_IP%:9001
echo    Redis Insight:     http://%LAN_IP%:5540
echo.
echo First run: open %PUBLIC_ORIGIN%/ and use the Keycloak Register link
echo to create your account. Then connect Spotify at http://%LAN_IP%:8888
echo and re-run this script to sync the library.

exit /b %BOOTSTRAP_RC%
