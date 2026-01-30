@echo off
:: PDF24 OCR Processor - Windows Service Installer
:: Requires NSSM (Non-Sucking Service Manager)
:: Download from: https://nssm.cc/download

setlocal

:: Configuration
set SERVICE_NAME=PDF24_OCR_Processor
set APP_DIR=%~dp0
set PYTHON_EXE=python.exe

:: Check for admin rights
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: This script requires Administrator privileges.
    echo Right-click and select "Run as administrator"
    pause
    exit /b 1
)

:: Check if NSSM exists
where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo NSSM not found in PATH.
    echo.
    echo Please download NSSM from: https://nssm.cc/download
    echo Extract and add nssm.exe to your PATH, or place it in this folder.
    echo.
    pause
    exit /b 1
)

echo ============================================
echo  PDF24 OCR Processor - Service Installer
echo ============================================
echo.
echo Service Name: %SERVICE_NAME%
echo App Directory: %APP_DIR%
echo.

:: Menu
echo What would you like to do?
echo [1] Install service
echo [2] Uninstall service
echo [3] Start service
echo [4] Stop service
echo [5] Check service status
echo [6] Open service manager (GUI)
echo [7] Exit
echo.
set /p choice="Enter choice (1-7): "

if "%choice%"=="1" goto install
if "%choice%"=="2" goto uninstall
if "%choice%"=="3" goto start
if "%choice%"=="4" goto stop
if "%choice%"=="5" goto status
if "%choice%"=="6" goto gui
if "%choice%"=="7" goto end

:install
echo.
echo Installing service...
nssm install %SERVICE_NAME% %PYTHON_EXE% -m streamlit run "%APP_DIR%app.py" --server.port 8501 --server.headless true
nssm set %SERVICE_NAME% AppDirectory "%APP_DIR%"
nssm set %SERVICE_NAME% DisplayName "PDF24 OCR Batch Processor"
nssm set %SERVICE_NAME% Description "Automated PDF OCR processing service using PDF24"
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% AppStdout "%APP_DIR%service_stdout.log"
nssm set %SERVICE_NAME% AppStderr "%APP_DIR%service_stderr.log"
nssm set %SERVICE_NAME% AppRotateFiles 1
nssm set %SERVICE_NAME% AppRotateBytes 1048576
echo.
echo Service installed. Starting service...
nssm start %SERVICE_NAME%
echo.
echo Service is now running at: http://localhost:8501
echo.
pause
goto end

:uninstall
echo.
echo Stopping service...
nssm stop %SERVICE_NAME% >nul 2>&1
echo Removing service...
nssm remove %SERVICE_NAME% confirm
echo Service uninstalled.
pause
goto end

:start
echo.
nssm start %SERVICE_NAME%
echo Service started. Access at: http://localhost:8501
pause
goto end

:stop
echo.
nssm stop %SERVICE_NAME%
echo Service stopped.
pause
goto end

:status
echo.
nssm status %SERVICE_NAME%
pause
goto end

:gui
echo.
echo Opening NSSM GUI for service editing...
nssm edit %SERVICE_NAME%
goto end

:end
endlocal
