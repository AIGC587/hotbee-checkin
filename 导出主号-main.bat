@echo off
setlocal
title 导出 WorkBuddy 主号 到云端
cd /d "%~dp0"
set "PYEXE=C:\Users\aisys\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
echo.
echo ============================================
echo   导出「主号」到云端档案 main
echo   前提：WorkBuddy 客户端当前登录的就是这个号
echo ============================================
echo.
"%PYEXE%" checkin_accounts.py whoami
echo.
echo 上面显示的就是要导出的账号，确认无误后继续（按任意键）...
pause >nul
"%PYEXE%" checkin_accounts.py add --alias main --from-client --sync --run --wait 120
echo.
echo 导出结束。若结果里 run.conclusion 为 success 即成功。
pause
