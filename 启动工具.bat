@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if "%errorlevel%"=="0" (
    py main.py
    goto :end
)
where python >nul 2>nul
if "%errorlevel%"=="0" (
    python main.py
    goto :end
)
echo 未找到 Python，请先安装 Python 3.10+ 并加入 PATH。
pause
:end
