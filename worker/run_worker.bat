@echo off
TITLE SSUBB GPU Worker Node v0.5
COLOR 0A
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

echo ========================================================
echo        SSUBB - Smart Subtitle Worker Node
echo        Version: 0.5.0
echo ========================================================
echo.

REM --- Python 检测 ---
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.10+ is required and was not found in PATH.
    pause
    exit /b 1
)

REM --- 依赖检查 ---
if not exist "worker\requirements.txt" (
    echo [ERROR] Missing worker\requirements.txt. Please run from the SSUBB root.
    pause
    exit /b 1
)

echo [INFO] Project root: %PROJECT_ROOT%
echo.

REM --- 首次配置引导 ---
if not exist "config.yaml" (
    echo [INFO] No config.yaml found. Starting setup wizard...
    echo.
    python -m worker.setup_wizard
    if %errorlevel% neq 0 (
        echo [ERROR] Setup wizard failed.
        pause
        exit /b 1
    )
) else (
    echo [INFO] config.yaml found, skipping setup wizard.
)

echo.
echo [INFO] Installing / checking Worker dependencies...
pip install -r "worker\requirements.txt" --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install Worker dependencies.
    pause
    exit /b 1
)

REM --- 环境检查 ---
echo.
echo [INFO] Running environment check...
python -m worker.env_check
if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Environment check reported issues. Continuing anyway...
    echo.
)

REM --- 启动 Worker ---
echo [INFO] Starting Worker service on http://0.0.0.0:8788 ...
echo.
python -m uvicorn worker.main:app --host 0.0.0.0 --port 8788

pause
