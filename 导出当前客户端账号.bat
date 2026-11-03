@echo off
setlocal
title 导出当前客户端登录的 WorkBuddy 账号
cd /d "%~dp0"
set "PYEXE=C:\Users\aisys\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
set "ALIAS=main"
if not "%~1"=="" set "ALIAS=%~1"
echo.
echo ============================================
echo   导出 WorkBuddy 客户端当前登录的账号
echo   用法: 导出当前客户端账号.bat main
echo         导出当前客户端账号.bat alt1
echo   请先确认客户端登录的就是要导出的那个号
echo ============================================
echo.
echo 目标档案别名: %ALIAS%
"%PYEXE%" checkin_accounts.py add --alias %ALIAS% --from-client --sync --run --wait 120
echo.
pause
