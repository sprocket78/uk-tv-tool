@echo off
rem Runs UK TV Tool with a visible console so any error stays on screen.
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
echo Using: %PY%
"%PY%" --version
"%PY%" -s -c "import yt_dlp, tkinter; print('yt-dlp', yt_dlp.version.__version__, '- tkinter ok')"
echo Starting app...
"%PY%" "%~dp0uk_tv_tool.py"
echo.
echo App exited with code %ERRORLEVEL%.
pause
