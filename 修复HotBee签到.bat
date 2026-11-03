@echo off
chcp 65001 >nul
title 修复 HotBee 自动签到
cd /d "%~dp0"

set "PYEXE=C:\Users\aisys\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

echo ============================================
echo  HotBee 签到自愈
echo  做的事：读取浏览器登录态 -> 校验令牌
echo          -> 写入云端 -> 触发一次签到
echo ============================================
echo.

"%PYEXE%" checkin_accounts.py hotbee-fix %*

echo.
echo 完成。如果上面出现 missing_local，说明该账号在浏览器里已退出登录，
echo 请登录 hotbee.cn 后再双击本文件一次。
echo.
pause
