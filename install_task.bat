@echo off
:: PDF24 OCR Processor - Windows Task Scheduler Installer
:: No external tools required - uses built-in Windows features

setlocal

:: Configuration
set TASK_NAME=PDF24_OCR_Worker
set APP_DIR=%~dp0
set WORKER_SCRIPT=%APP_DIR%worker.pyw

:: Find pythonw.exe full path (SYSTEM user doesn't have user PATH)
for /f "delims=" %%i in ('where pythonw 2^>nul') do (
    set PYTHONW_PATH=%%i
    goto :found_python
)
echo.
echo ============================================
echo  ERROR: Python not found!
echo ============================================
echo.
echo pythonw.exe was not found in your system PATH.
echo.
echo Please install Python:
echo   1. Download from: https://www.python.org/downloads/
echo   2. Run the installer
echo   3. IMPORTANT: Check "Add Python to PATH" during installation
echo   4. Restart your computer
echo   5. Run this script again
echo.
echo Recommended: Python 3.10 or later
echo.
pause
exit /b 1

:found_python
echo Python found: %PYTHONW_PATH%

:: Check for admin rights
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: This script requires Administrator privileges.
    echo Right-click and select "Run as administrator"
    pause
    exit /b 1
)

echo ============================================
echo  PDF24 OCR Processor - Task Scheduler Setup
echo ============================================
echo.
echo Task Name: %TASK_NAME%
echo Worker Script: %WORKER_SCRIPT%
echo Python: %PYTHONW_PATH%
echo.

:: Menu
echo What would you like to do?
echo.
echo [1] Install background worker (runs on startup)
echo [2] Uninstall task
echo [3] Start task now
echo [4] Stop task
echo [5] Check task status
echo [6] Exit
echo.
set /p choice="Enter choice (1-6): "

if "%choice%"=="1" goto install
if "%choice%"=="2" goto uninstall
if "%choice%"=="3" goto start
if "%choice%"=="4" goto stop
if "%choice%"=="5" goto status
if "%choice%"=="6" goto end

:install
echo.
echo Installing background worker task...
echo.

:: Delete existing task if present
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

:: Create the scheduled task
:: - Runs at system startup
:: - Runs whether user is logged in or not
:: - Restarts on failure (up to 3 times, every 1 minute)
:: - Runs with highest privileges

schtasks /create /tn "%TASK_NAME%" /tr "\"%PYTHONW_PATH%\" \"%WORKER_SCRIPT%\"" /sc onstart /ru SYSTEM /rl highest /f

if %errorlevel% neq 0 (
    echo.
    echo Failed to create task. Trying alternative method...
    :: Alternative: run at logon instead of system startup
    schtasks /create /tn "%TASK_NAME%" /tr "\"%PYTHONW_PATH%\" \"%WORKER_SCRIPT%\"" /sc onlogon /rl highest /f
)

:: Configure restart on failure using PowerShell
powershell -Command "$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable; $task = Get-ScheduledTask -TaskName '%TASK_NAME%'; Set-ScheduledTask -TaskName '%TASK_NAME%' -Settings $settings"

echo.
echo ============================================
echo  Task installed successfully!
echo ============================================
echo.
echo  - Starts automatically on Windows boot
echo  - Restarts on failure (every 1 minute, unlimited retries)
echo  - Checks for files every 60 seconds
echo  - Logs at: %APP_DIR%worker.log
echo  - Settings from: auto_start.json
echo.
echo Starting task now...
schtasks /run /tn "%TASK_NAME%"
echo.
echo Task is now running in background!
echo.
pause
goto end

:uninstall
echo.
echo Stopping and removing task...
schtasks /end /tn "%TASK_NAME%" >nul 2>&1
schtasks /delete /tn "%TASK_NAME%" /f
echo Task uninstalled.
pause
goto end

:start
echo.
schtasks /run /tn "%TASK_NAME%"
echo Task started.
pause
goto end

:stop
echo.
schtasks /end /tn "%TASK_NAME%"
echo Task stopped.
pause
goto end

:status
echo.
echo Task Status:
echo ------------
schtasks /query /tn "%TASK_NAME%" /v /fo list | findstr /i "Status State"
echo.
echo Running Processes:
tasklist /fi "imagename eq pythonw.exe" 2>nul | findstr /i "pythonw"
if %errorlevel% neq 0 echo No pythonw.exe processes found
echo.
pause
goto end

:end
endlocal
