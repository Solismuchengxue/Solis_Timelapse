@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Sony 延时摄影 WebUI

echo.
echo   Sony 延时摄影 WebUI —— 正在启动...
echo.

if not exist ".venv\Scripts\python.exe" (
    where python >nul 2>nul
    if errorlevel 1 (
        echo   未找到 Python。请安装 Python 3.12 并勾选 Add Python to PATH。
        echo.
        pause
        exit /b 1
    )
    echo   [首次启动] 正在创建虚拟环境并安装依赖...
    python -m venv .venv
    if errorlevel 1 (
        echo   创建 .venv 失败，请运行 python --version 检查环境。
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo   安装依赖失败，请检查网络和 requirements.txt。
        pause
        exit /b 1
    )
)

.venv\Scripts\python.exe webui\server.py

echo.
echo   WebUI 已停止。
pause
