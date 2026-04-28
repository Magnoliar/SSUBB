#!/bin/bash
# SSUBB Coordinator - NAS 端启动脚本

set -e
cd "$(dirname "$0")"

echo "========================================================"
echo "       SSUBB Coordinator - NAS 端控制中心"
echo "========================================================"
echo

# --- Python 检测 ---
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python3，请先安装 Python 3.10+"
    exit 1
fi

# --- FFmpeg 检测 ---
if ! command -v ffmpeg &> /dev/null; then
    echo "[警告] 未找到 FFmpeg，音频提取功能不可用"
    echo "       Ubuntu/Debian: sudo apt install ffmpeg"
    echo "       macOS: brew install ffmpeg"
    echo
fi

# --- 首次配置引导 ---
if [ ! -f "config.yaml" ]; then
    echo "[提示] 首次运行，正在启动配置向导..."
    echo
    python3 -m coordinator.setup_wizard
    if [ $? -ne 0 ]; then
        echo "[错误] 配置向导未完成。"
        exit 1
    fi
else
    echo "[提示] 检测到 config.yaml，跳过配置向导。"
fi

# --- 安装依赖 ---
echo "[信息] 检查并安装依赖..."
pip3 install -r coordinator/requirements.txt --quiet

# --- 启动 ---
echo
echo "[信息] 正在启动 Coordinator..."
echo "[信息] 控制台地址: http://localhost:8787"
echo "[信息] 按 Ctrl+C 停止服务"
echo
python3 -m uvicorn coordinator.main:app --host 0.0.0.0 --port 8787
