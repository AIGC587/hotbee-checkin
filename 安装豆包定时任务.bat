@echo off
setlocal
chcp 936 >nul
title 安装豆包签到定时任务
cd /d "%~dp0"
set "PYW=C:\Users\aisys\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
set "SCRIPT=E:\WorkBuddy\自动签到\doubao_checkin.py"

echo ============================================
echo   安装「豆包每日签到」计划任务
echo   触发：每天 09:10 + 每次登录后 5 分钟
echo ============================================
echo.

schtasks /Create /TN "DoubaoCheckin" /TR "\"%PYW%\" \"%SCRIPT%\"" /SC DAILY /ST 09:10 /F
if errorlevel 1 goto fail

schtasks /Create /TN "DoubaoCheckinLogon" /TR "\"%PYW%\" \"%SCRIPT%\"" /SC ONLOGON /DELAY 0005:00 /F
if errorlevel 1 echo [提示] 登录触发未装上（可能需要管理员权限），不影响每天 09:10 那次。

echo.
echo 安装完成。可以现在手动跑一次测试：
schtasks /Run /TN "DoubaoCheckin"
echo.
echo 日志：_logs\doubao-checkin.log
pause
exit /b 0

:fail
echo.
echo [失败] 任务创建失败，请右键本文件「以管理员身份运行」后重试。
pause
exit /b 1
