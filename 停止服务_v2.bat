@echo off
chcp 65001 >nul
title WebAPI 停止服务

echo.
echo ========================================
echo        WebAPI 服务停止程序
echo ========================================
echo.

:: 检查Python进程
echo [1/4] 检查Python进程...
tasklist /fi "imagename eq python.exe" | find "python.exe" >nul
if %errorlevel% equ 0 (
    echo    [发现] 检测到Python进程
    echo    [停止] 正在停止Python进程...
    taskkill /f /im python.exe >nul 2>&1
    if %errorlevel% equ 0 (
        echo    [成功] Python进程已停止
    ) else (
        echo    [警告] Python进程停止失败
    )
) else (
    echo    [正常] 未检测到Python进程
)

:: 检查Uvicorn进程
echo.
echo [2/4] 检查Uvicorn进程...
tasklist /fi "imagename eq uvicorn.exe" | find "uvicorn.exe" >nul
if %errorlevel% equ 0 (
    echo    [发现] 检测到Uvicorn进程
    echo    [停止] 正在停止Uvicorn进程...
    taskkill /f /im uvicorn.exe >nul 2>&1
    if %errorlevel% equ 0 (
        echo    [成功] Uvicorn进程已停止
    ) else (
        echo    [警告] Uvicorn进程停止失败
    )
) else (
    echo    [正常] 未检测到Uvicorn进程
)

:: 检查端口18080
echo.
echo [3/4] 检查端口18080...
netstat -ano | findstr :18080 >nul
if %errorlevel% equ 0 (
    echo    [发现] 端口18080被占用
    echo    [停止] 正在查找占用端口的进程...
    
    :: 获取进程ID
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :18080') do set pid=%%a
    
    if defined pid (
        echo    [信息] 进程ID: %pid%
        echo    [停止] 正在停止进程...
        taskkill /f /pid %pid% >nul 2>&1
        if %errorlevel% equ 0 (
            echo    [成功] 端口18080已释放
        ) else (
            echo    [警告] 端口18080释放失败
        )
    ) else (
        echo    [警告] 无法获取占用端口的进程ID
    )
) else (
    echo    [正常] 端口18080未被占用
)

:: 检查WebAPI相关进程
echo.
echo [4/4] 检查WebAPI进程...
tasklist /fi "imagename eq webapi.exe" | find "webapi.exe" >nul
if %errorlevel% equ 0 (
    echo    [发现] 检测到WebAPI进程
    echo    [停止] 正在停止WebAPI进程...
    taskkill /f /im webapi.exe >nul 2>&1
    if %errorlevel% equ 0 (
        echo    [成功] WebAPI进程已停止
    ) else (
        echo    [警告] WebAPI进程停止失败
    )
) else (
    echo    [正常] 未检测到WebAPI进程
)

echo.
echo ========================================
echo           停止服务完成
echo ========================================
echo.

:: 验证服务状态
echo [验证] 检查服务状态...
netstat -ano | findstr :18080 >nul
if %errorlevel% equ 0 (
    echo    [警告] 端口18080仍被占用，服务可能未完全停止
    echo    [建议] 请手动检查任务管理器
) else (
    echo    [成功] WebAPI服务已完全停止
    echo    [信息] 端口18080已释放
)

echo.
echo 按任意键退出...
pause >nul