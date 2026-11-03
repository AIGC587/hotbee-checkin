@echo off
setlocal
title 导出 小号（alt1）
cd /d "%~dp0"
set "PYEXE=C:\Users\aisys\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
echo.
echo ============================================
echo   即将把「客户端当前登录的账号」导出为 小号（alt1）
echo ============================================
echo.
echo [1] 当前客户端登录的是：
"%PYEXE%" checkin_accounts.py peek
echo.
echo 请确认上面的昵称/手机号就是 小号。
echo 如果不对，直接关掉本窗口，先切换账号。
echo.
echo 确认无误按任意键继续导出，否则按 Ctrl+C 取消...
pause >nul
echo.
echo [2] 开始导出并同步云端...
"%PYEXE%" checkin_accounts.py add --alias alt1 --from-client --sync --run --wait 120
echo.
echo 完成。run.conclusion 为 success 即成功。
pause
