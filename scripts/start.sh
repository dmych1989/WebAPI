#!/bin/bash
# WebAPI 启动脚本 (Linux/macOS)

set -e

echo "============================================"
echo " WebAPI - 网页版大模型对话转本地API调用"
echo "============================================"
echo

cd "$(dirname "$0")/.."

echo "[1/2] Checking Python..."
python3 --version

echo "[2/2] Starting WebAPI server..."
echo
python3 -m src.main "$@"
