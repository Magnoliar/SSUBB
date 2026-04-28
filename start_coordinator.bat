@echo off
TITLE SSUBB Coordinator (NAS 端)
COLOR 0B
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo ========================================================
echo        SSUBB Coordinator - NAS 端控制中心
echo ========================================================
echo.

REM --- Python 检测 ---
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10 以上版本。
    echo        下载地址: https://www.python.org/downloads/
    echo        安装时记得勾选 "Add Python to PATH"
    pause
    exit /b 1
)

REM --- FFmpeg 检测 ---
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] 未找到 FFmpeg，音频提取功能不可用。
    echo        下载地址: https://www.gyan.dev/ffmpeg/builds/
    echo        下载后把 ffmpeg.exe 放到 PATH 目录即可。
    echo.
)

REM --- 首次配置引导 ---
if not exist "config.yaml" (
    echo [提示] 首次运行，正在启动配置向导...
    echo.
    python -m coordinator.setup_wizard
    if %errorlevel% neq 0 (
        echo [错误] 配置向导未完成。
        pause
        exit /b 1
    )
) else (
    echo [提示] 检测到 config.yaml，跳过配置向导。
)

REM --- 安装依赖 ---
echo [信息] 检查并安装依赖...
pip install -r coordinator\requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败，请检查网络连接。
    pause
    exit /b 1
)

REM --- 启动服务 ---
echo.
echo [信息] 正在启动 Coordinator...
echo [信息] 控制台地址: http://localhost:8787
echo [信息] 按 Ctrl+C 停止服务
echo.
python -m uvicorn coordinator.main:app --host 0.0.0.0 --port 8787

pause
