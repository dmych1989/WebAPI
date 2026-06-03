@echo off
chcp 65001 >nul
title WebAPI Server

echo ============================================
echo  WebAPI - 网页版大模型对话转本地API调用
echo ============================================
echo.

cd /d "%~dp0.."

echo [1/2] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found!
    pause
    exit /b 1
)

echo [2/2] Starting WebAPI server...
echo.
python -m src.main %*

pause
