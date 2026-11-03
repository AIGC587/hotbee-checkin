@echo off
chcp 65001 >nul
title 导出当前客户端登录的 WorkBuddy 账号
cd /d "%~dp0"

set "PYEXE=C:\Users\aisys\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

echo ============================================
echo  把「客户端当前登录的账号」导出到云端
echo  用法：先在本文件上右键-编辑，把下面的 ALIAS 改成 main 或 alt1
echo        然后确保 WorkBuddy 客户端登录的就是要导出的那个号
echo ============================================
echo.

set "ALIAS=main"
if not "%~1"=="" set "ALIAS=%~1"

echo 目标档案别名：%ALIAS%
echo 正在读取客户端当前登录账号...
"%PYEXE%" checkin_accounts.py add --alias %ALIAS% --from-client --sync --run --wait 120

echo.
pause
