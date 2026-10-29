@echo off
rem Starts UK TV Tool without a console window.
cd /d "%~dp0"
set "LOG=%APPDATA%\iplayer-dl\launch.log"
if not exist "%APPDATA%\iplayer-dl" mkdir "%APPDATA%\iplayer-dl"
set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
echo [%DATE% %TIME%] dir=%CD% python=%PYW% > "%LOG%"
start "" "%PYW%" "%~dp0uk_tv_tool.py"
echo start exit code: %ERRORLEVEL% >> "%LOG%"
