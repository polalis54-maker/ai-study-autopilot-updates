@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo =============================================
echo  AI Study Autopilot - Live Status
echo =============================================
echo.
set "PAGE=%~dp0work\outputs\runtime_status.html"
if exist "%PAGE%" goto open_page
set "PAGE=%~dp0work\outputs\live_progress.html"
if exist "%PAGE%" goto old_page
echo [WARN] Status HTML was not found.
echo [INFO] Check that START_AUTOPILOT.cmd is running.
echo [INFO] Open CHECK_RUNNING.cmd for more details.
goto end
:old_page
echo [INFO] Only the old progress page exists.
echo [INFO] Restart the background process to enable live status.
:open_page
echo [OK] Found status page:
echo "%PAGE%"
echo [INFO] Opening your default browser...
start "" "%PAGE%"
if errorlevel 1 goto launch_error
echo [INFO] If no browser appears, open the above file from Explorer.
goto end
:launch_error
echo [ERROR] Windows could not open the status HTML.
echo [INFO] Open the file shown above directly with Explorer.
:end
echo.
echo [INFO] This window will stay open until you press a key.
pause
exit /b 0
