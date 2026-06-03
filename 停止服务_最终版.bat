@echo off
title WebAPI Stop Service

echo WebAPI Service Stop Program
echo =============================

echo [1/4] Checking Python processes...
tasklist /fi "imagename eq python.exe" | find "python.exe" >nul
if %errorlevel% equ 0 (
    echo    Found Python process, stopping...
    taskkill /f /im python.exe >nul 2>&1
    if %errorlevel% equ 0 (
        echo    Python process stopped successfully
    ) else (
        echo    Failed to stop Python process
    )
) else (
    echo    No Python process found
)

echo.
echo [2/4] Checking Uvicorn processes...
tasklist /fi "imagename eq uvicorn.exe" | find "uvicorn.exe" >nul
if %errorlevel% equ 0 (
    echo    Found Uvicorn process, stopping...
    taskkill /f /im uvicorn.exe >nul 2>&1
    if %errorlevel% equ 0 (
        echo    Uvicorn process stopped successfully
    ) else (
        echo    Failed to stop Uvicorn process
    )
) else (
    echo    No Uvicorn process found
)

echo.
echo [3/4] Checking port 18080...
netstat -ano | findstr :18080 >nul
if %errorlevel% equ 0 (
    echo    Port 18080 is in use, finding process...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :18080') do set pid=%%a
    if defined pid (
        echo    Process ID: %%pid%%
        echo    Stopping process...
        taskkill /f /pid %%pid%% >nul 2>&1
        if %errorlevel% equ 0 (
            echo    Port 18080 released successfully
        ) else (
            echo    Failed to release port 18080
        )
    ) else (
        echo    Cannot find process ID for port 18080
    )
) else (
    echo    Port 18080 is free
)

echo.
echo [4/4] Checking WebAPI processes...
tasklist /fi "imagename eq webapi.exe" | find "webapi.exe" >nul
if %errorlevel% equ 0 (
    echo    Found WebAPI process, stopping...
    taskkill /f /im webapi.exe >nul 2>&1
    if %errorlevel% equ 0 (
        echo    WebAPI process stopped successfully
    ) else (
        echo    Failed to stop WebAPI process
    )
) else (
    echo    No WebAPI process found
)

echo.
echo Service Stop Complete
echo =============================

echo Verifying service status...
netstat -ano | findstr :18080 >nul
if %errorlevel% equ 0 (
    echo    WARNING: Port 18080 still in use
    echo    Please check Task Manager manually
) else (
    echo    SUCCESS: WebAPI service fully stopped
    echo    Port 18080 released
)

echo.
echo Press any key to exit...
pause >nul