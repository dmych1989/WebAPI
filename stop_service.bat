@echo off
chcp 65001 >nul
title WebAPI Stop Service

echo.
echo ========================================
echo        WebAPI Service Stop Program
echo ========================================
echo.

:: Check Python processes
echo [1/4] Checking Python processes...
tasklist /fi "imagename eq python.exe" | find "python.exe" >nul
if %errorlevel% equ 0 (
    echo    [Found] Python process detected
    echo    [Stopping] Stopping Python process...
    taskkill /f /im python.exe >nul 2>&1
    if %errorlevel% equ 0 (
        echo    [Success] Python process stopped
    ) else (
        echo    [Warning] Failed to stop Python process
    )
) else (
    echo    [Normal] No Python process found
)

:: Check Uvicorn processes
echo.
echo [2/4] Checking Uvicorn processes...
tasklist /fi "imagename eq uvicorn.exe" | find "uvicorn.exe" >nul
if %errorlevel% equ 0 (
    echo    [Found] Uvicorn process detected
    echo    [Stopping] Stopping Uvicorn process...
    taskkill /f /im uvicorn.exe >nul 2>&1
    if %errorlevel% equ 0 (
        echo    [Success] Uvicorn process stopped
    ) else (
        echo    [Warning] Failed to stop Uvicorn process
    )
) else (
    echo    [Normal] No Uvicorn process found
)

:: Check port 18080
echo.
echo [3/4] Checking port 18080...
netstat -ano | findstr :18080 >nul
if %errorlevel% equ 0 (
    echo    [Found] Port 18080 is in use
    echo    [Stopping] Finding process using port...
    
    :: Get PID of process using port
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :18080') do set pid=%%a
    
    echo    [Info] Process ID: %pid%
    echo    [Stopping] Stopping process...
    taskkill /f /pid %pid% >nul 2>&1
    if %errorlevel% equ 0 (
        echo    [Success] Port 18080 released
    ) else (
        echo    [Warning] Failed to release port 18080
    )
) else (
    echo    [Normal] Port 18080 is free
)

:: Check WebAPI processes
echo.
echo [4/4] Checking WebAPI processes...
tasklist /fi "imagename eq webapi.exe" | find "webapi.exe" >nul
if %errorlevel% equ 0 (
    echo    [Found] WebAPI process detected
    echo    [Stopping] Stopping WebAPI process...
    taskkill /f /im webapi.exe >nul 2>&1
    if %errorlevel% equ 0 (
        echo    [Success] WebAPI process stopped
    ) else (
        echo    [Warning] Failed to stop WebAPI process
    )
) else (
    echo    [Normal] No WebAPI process found
)

echo.
echo ========================================
echo           Service Stop Complete
echo ========================================
echo.

:: Verify service is stopped
echo [Verification] Checking service status...
netstat -ano | findstr :18080 >nul
if %errorlevel% equ 0 (
    echo    [Warning] Port 18080 still in use, service may not be fully stopped
    echo    [Suggestion] Please check Task Manager manually
) else (
    echo    [Success] WebAPI service fully stopped
    echo    [Info] Port 18080 released
)

echo.
echo Press any key to exit...
pause >nul