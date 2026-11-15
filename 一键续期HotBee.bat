@echo off
setlocal enabledelayedexpansion
title HotBee 一键续期
cd /d "%~dp0"
if /i "%~1"=="test" set "NOPAUSE=1"
set "PYEXE=C:/Users/aisys/.workbuddy/binaries/python/versions/3.13.12/python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
echo ============================================
echo    HotBee 一键续期（每次处理一个账号）
echo ============================================
echo.
echo 操作步骤：
echo   [1] 浏览器打开 https://hotbee.cn 并登录要续期的账号
echo   [2] 按 F12 打开 Console，粘贴下面这一行后回车：
echo.
echo         copy(localStorage.getItem('token'))
echo.
echo   [3] 回到本窗口，输入账号编号
echo.
echo     [1] 152****2587  (hb1)
echo     [2] 198****2587  (hb2)
echo.
set /p SEL=请输入 1 或 2 后回车：
if "%SEL%"=="1" set "ALIAS=hb1"
if "%SEL%"=="2" set "ALIAS=hb2"
if not defined ALIAS (
  echo 输入无效，已退出。
  if not defined NOPAUSE pause
  exit /b 1
)
echo.
echo 用剪贴板里的令牌续期 %ALIAS% ...
echo --------------------------------------------
"%PYEXE%" checkin_accounts.py hotbee-fix --alias %ALIAS% --from-clipboard
set "RC=%ERRORLEVEL%"
echo --------------------------------------------
if "%RC%"=="0" (
  echo 续期完成，云端已更新并触发一次签到。
) else (
  echo 续期未完成（返回码 %RC%）。
  echo 常见原因：剪贴板里不是令牌 / 该账号登录态已失效 / GitHub 令牌过期。
)
echo.
echo 换另一个账号：登录 -^> 复制令牌 -^> 再双击本文件。
if not defined NOPAUSE pause
