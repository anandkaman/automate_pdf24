@echo off
:: PDF24 OCR Processor - Windows Service Installer
:: Requires NSSM (Non-Sucking Service Manager)
:: Download from: https://nssm.cc/download

setlocal

:: Configuration
set SERVICE_NAME=PDF24_OCR_Worker
set APP_DIR=%~dp0
set PYTHON_EXE=pythonw.exe

:: Check for admin rights
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: This script requires Administrator privileges.
    echo Right-click and select "Run as administrator"
    pause
    exit /b 1
)

:: Check if NSSM exists in current folder or PATH
if exist "%APP_DIR%nssm.exe" (
    set NSSM_EXE=%APP_DIR%nssm.exe
) else (
    where nssm >nul 2>&1
    if %errorlevel% neq 0 (
        echo NSSM not found!
        echo.
        echo Please download NSSM from: https://nssm.cc/download
        echo Extract and copy nssm.exe to: %APP_DIR%
        echo.
        pause
        exit /b 1
    )
    set NSSM_EXE=nssm
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
echo.
echo [1] Install background worker (NO browser needed - recommended)
echo [2] Install Streamlit UI service (browser at localhost:8501)
echo [3] Uninstall service
echo [4] Start service
echo [5] Stop service
echo [6] Check service status
echo [7] Exit
echo.
set /p choice="Enter choice (1-7): "

if "%choice%"=="1" goto install_worker
if "%choice%"=="2" goto install_streamlit
if "%choice%"=="3" goto uninstall
if "%choice%"=="4" goto start
if "%choice%"=="5" goto stop
if "%choice%"=="6" goto status
if "%choice%"=="7" goto end

:install_worker
echo.
echo Installing background worker service...
echo This runs silently - no browser needed!
echo.
"%NSSM_EXE%" install %SERVICE_NAME% %PYTHON_EXE% "%APP_DIR%worker.pyw"
"%NSSM_EXE%" set %SERVICE_NAME% AppDirectory "%APP_DIR%"
"%NSSM_EXE%" set %SERVICE_NAME% DisplayName "PDF24 OCR Background Worker"
"%NSSM_EXE%" set %SERVICE_NAME% Description "Automated PDF OCR processing - checks for files every minute"
"%NSSM_EXE%" set %SERVICE_NAME% Start SERVICE_AUTO_START
"%NSSM_EXE%" set %SERVICE_NAME% AppStdout "%APP_DIR%service_stdout.log"
"%NSSM_EXE%" set %SERVICE_NAME% AppStderr "%APP_DIR%service_stderr.log"
"%NSSM_EXE%" set %SERVICE_NAME% AppRotateFiles 1
"%NSSM_EXE%" set %SERVICE_NAME% AppRotateBytes 1048576
:: Auto-restart on crash
"%NSSM_EXE%" set %SERVICE_NAME% AppExit Default Restart
"%NSSM_EXE%" set %SERVICE_NAME% AppRestartDelay 10000
echo.
echo Service installed! Starting...
"%NSSM_EXE%" start %SERVICE_NAME%
echo.
echo ============================================
echo  Worker is now running in background!
echo ============================================
echo.
echo  - Starts automatically on Windows boot
echo  - Restarts automatically if it crashes (10 sec delay)
echo  - Checks for files every 60 seconds
echo  - Logs at: %APP_DIR%worker.log
echo  - Settings from: auto_start.json
echo.
pause
goto end

:install_streamlit
echo.
echo Installing Streamlit UI service...
"%NSSM_EXE%" install %SERVICE_NAME% python -m streamlit run "%APP_DIR%app.py" --server.port 8501 --server.headless true
"%NSSM_EXE%" set %SERVICE_NAME% AppDirectory "%APP_DIR%"
"%NSSM_EXE%" set %SERVICE_NAME% DisplayName "PDF24 OCR Processor (Streamlit)"
"%NSSM_EXE%" set %SERVICE_NAME% Description "PDF OCR web UI at http://localhost:8501"
"%NSSM_EXE%" set %SERVICE_NAME% Start SERVICE_AUTO_START
"%NSSM_EXE%" set %SERVICE_NAME% AppStdout "%APP_DIR%service_stdout.log"
"%NSSM_EXE%" set %SERVICE_NAME% AppStderr "%APP_DIR%service_stderr.log"
echo.
echo Service installed! Starting...
"%NSSM_EXE%" start %SERVICE_NAME%
echo.
echo Streamlit is now running at: http://localhost:8501
echo.
pause
goto end

:uninstall
echo.
echo Stopping service...
"%NSSM_EXE%" stop %SERVICE_NAME% >nul 2>&1
echo Removing service...
"%NSSM_EXE%" remove %SERVICE_NAME% confirm
echo Service uninstalled.
pause
goto end

:start
echo.
"%NSSM_EXE%" start %SERVICE_NAME%
echo Service started.
pause
goto end

:stop
echo.
"%NSSM_EXE%" stop %SERVICE_NAME%
echo Service stopped.
pause
goto end

:status
echo.
"%NSSM_EXE%" status %SERVICE_NAME%
pause
goto end

:end
endlocal
