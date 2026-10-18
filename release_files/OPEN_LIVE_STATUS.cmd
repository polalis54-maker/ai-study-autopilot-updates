@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "work\outputs\runtime_status.html" (
  start "" "work\outputs\runtime_status.html"
  exit /b 0
)
if exist "work\outputs\live_progress.html" (
  echo 最新の稼働表示を有効にするには一度バックグラウンド常駐を再起動してください。
  start "" "work\outputs\live_progress.html"
  exit /b 0
)
py -3 check_running.py
pause
