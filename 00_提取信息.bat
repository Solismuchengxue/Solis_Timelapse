@echo off
chcp 65001 >nul
cd /d "%~dp0"
"D:\Python3_12\python.exe" "02_program\s00_extract_info.py"
echo.
pause
