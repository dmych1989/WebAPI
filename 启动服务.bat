@echo off
chcp 65001 >nul
title WebAPI 服务 - 端口 18080

cd /d D:\GitHub\WebAPI

echo.
echo ============================================
echo   WebAPI 服务启动中...
echo   端口: 18080
echo   Admin: http://127.0.0.1:18080/admin/ui/admin.html
echo   API:   http://127.0.0.1:18080/v1/chat/completions
echo ============================================
echo.

python -m src.main --port 18080

pause