@echo off
REM ============================================
REM   WebAPI 一键启动脚本
REM   - 自动激活虚拟环境（如有）
REM   - 后台启动 uvicorn 服务
REM   - 自动打开浏览器到管理界面
REM ============================================

chcp 65001 >nul
cd /d "%~dp0"

REM 选择 Python 解释器（优先使用 .venv）
set "PYTHON=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
)

echo.
echo ============================================
echo   WebAPI 启动中...
echo ============================================
echo.

REM 检查端口 18080 是否被占用
netstat -ano | findstr :18080 | findstr LISTENING >nul
if %errorlevel% equ 0 (
    echo [警告] 端口 18080 已被占用，将复用现有服务
    echo.
) else (
    REM 后台启动 uvicorn 到新窗口（方便查看日志 + Ctrl+C 停止）
    echo 启动 uvicorn 服务...
    start "WebAPI Server" cmd /k "%PYTHON% -m uvicorn src.server.app:app --host 127.0.0.1 --port 18080"
    echo.
    echo 等待服务就绪...
    timeout /t 4 /nobreak >nul
)

REM 自动打开浏览器到管理界面
echo 打开管理界面...
start "" "http://127.0.0.1:18080/admin/ui"

echo.
echo ============================================
echo   WebAPI 已启动
echo ============================================
echo   服务地址:   http://127.0.0.1:18080
echo   管理界面:   http://127.0.0.1:18080/admin/ui
echo   API 文档:   http://127.0.0.1:18080/v1/docs
echo   健康检查:   http://127.0.0.1:18080/health
echo.
echo   停止服务: 在 WebAPI Server 窗口按 Ctrl+C
echo ============================================
echo.
pause
