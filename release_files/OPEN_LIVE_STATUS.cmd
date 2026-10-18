@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ===============================================
echo   AI Study Autopilot - 稼働ダッシュボード
echo ===============================================
echo.
if exist "%~dp0work\outputs\runtime_status.html" (
  echo [OK] 稼働状況の画面を見つけました。
  echo [INFO] 既定のブラウザで開きます。
  start "" "%~dp0work\outputs\runtime_status.html"
  goto :confirm
)
if exist "%~dp0work\outputs\live_progress.html" (
  echo [INFO] 旧版の進捗画面を見つけました。
  echo [INFO] 新しい稼働表示は常駐を再起動すると有効になります。
  start "" "%~dp0work\outputs\live_progress.html"
  goto :confirm
)
echo [WARN] 進捗画面がまだありません。
echo [INFO] 常駐を起動していないか、初回の状態ファイル作成前の可能性があります。
echo.
if exist "%~dp0check_running.py" (
  py -3 "%~dp0check_running.py"
) else (
  echo [WARN] CHECK_RUNNING.cmd から状態をご確認ください。
)
goto :end
:confirm
echo.
echo [INFO] ブラウザが開かない場合は、work\outputs にある
echo        runtime_status.html または live_progress.html を直接開いてください。
echo [INFO] 画面には8秒おきの自動更新を設定しています。
:end
echo.
echo [INFO] この確認画面はキーを押すまで閉じません。
pause
exit /b 0
