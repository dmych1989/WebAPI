@echo off
chcp 65001 >nul
title 停止 WebAPI 服务

echo.
echo ============================================
echo   正在停止 WebAPI 服务 (端口 18080)...
echo ============================================

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18080" ^| findstr "LISTENING"') do (
    echo   找到进程 PID: %%a，正在终止...
    taskkill /f /pid %%a >nul 2>&1
    echo   进程 %%a 已终止
)

echo.
echo   服务已停止。
echo ============================================

timeout /t 2 >nul