@echo off
setlocal
title 豆包每日签到
cd /d "%~dp0"
set "PYEXE=C:\Users\aisys\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
echo.
echo ============================================
echo   豆包每日签到（自动点击「立即签到」）
echo   会打开豆包的活动页窗口，签完自动关闭提示
echo ============================================
echo.
"%PYEXE%" doubao_checkin.py
echo.
echo 结果已写入 _logs\doubao-checkin.log
echo.
pause
