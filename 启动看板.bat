@echo off
chcp 65001 >nul
title GEO Dashboard
pushd "%~dp0dashboard"
if not exist app.py (
  echo [ERROR] Could not find app.py in the dashboard folder.
  echo Make sure this .bat sits next to the dashboard folder.
  pause
  exit /b 1
)
echo ============================================
echo   Starting GEO Dashboard ...
echo   A browser tab will open at http://127.0.0.1:5000
echo   To stop: just close this window.
echo ============================================
start "" http://127.0.0.1:5000
python app.py || py app.py
popd
pause
