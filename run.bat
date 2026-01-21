@echo off
chcp 65001 >nul
title Meshtastic COT 广播+TCP双模式同步运行
set INTERVAL=10
set "PY_FILE=meshtastic_cot.py"

echo ======================================
echo  双模式同步运行中（均每%INTERVAL%s发送一次）
echo  ✅ 广播模式：默认配置（可改下方参数）
echo  ✅ TCP模式：默认配置（可改下方参数）
echo  =====================================
echo  按 Ctrl+C 一键停止所有进程
echo ======================================
echo.

:: 启动广播模式（后台运行，不阻塞）
start "Meshtastic-广播模式" cmd /k python %PY_FILE% --proto broadcast --interval %INTERVAL%

:: 启动TCP模式（前台显示日志，方便查看）
python %PY_FILE% --proto tcp --interval %INTERVAL%

:: 关闭信号：前台TCP停止时，自动杀掉后台广播进程
taskkill /f /im cmd.exe /fi "WINDOWTITLE eq Meshtastic-广播模式" >nul 2>&1
echo.
echo 所有模式已停止
pause
