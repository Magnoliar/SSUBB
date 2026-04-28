#!/bin/bash
# SSUBB Worker Node 启动脚本 (Linux/macOS)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "========================================================"
echo "       SSUBB - Smart Subtitle Worker Node"
echo "       Version: 0.5.0"
echo "========================================================"
echo

# --- Python 检测 ---
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3.10+ is required and was not found."
    exit 1
fi

PYTHON_VER=$(python3 --version 2>&1)
echo "[INFO] $PYTHON_VER"
echo "[INFO] Project root: $PROJECT_ROOT"
echo

# --- 首次配置引导 ---
if [ ! -f "config.yaml" ]; then
    echo "[INFO] No config.yaml found. Starting setup wizard..."
    echo
    python3 -m worker.setup_wizard
    if [ $? -ne 0 ]; then
        echo "[ERROR] Setup wizard failed."
        exit 1
    fi
else
    echo "[INFO] config.yaml found, skipping setup wizard."
fi

echo
echo "[INFO] Installing / checking Worker dependencies..."
pip3 install -r "worker/requirements.txt" --quiet
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to install Worker dependencies."
    exit 1
fi

# --- 环境检查 ---
echo
echo "[INFO] Running environment check..."
python3 -m worker.env_check || echo "[WARNING] Environment check reported issues."

# --- 启动 Worker ---
echo
echo "[INFO] Starting Worker service on http://0.0.0.0:8788 ..."
echo
python3 -m uvicorn worker.main:app --host 0.0.0.0 --port 8788
