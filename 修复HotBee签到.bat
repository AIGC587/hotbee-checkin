@echo off
setlocal
title HotBee 签到自愈
cd /d "%~dp0"
set "PYEXE=C:\Users\aisys\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
echo.
echo ============================================
echo   HotBee 签到自愈
echo   读取浏览器登录态 - 校验令牌 - 写云端 - 触发签到
echo ============================================
echo.
"%PYEXE%" checkin_accounts.py hotbee-fix %*
echo.
echo 完成。若上面出现 missing_local，说明该账号已在浏览器退出登录，
echo 请先登录 hotbee.cn，再双击本文件一次。
echo.
pause
