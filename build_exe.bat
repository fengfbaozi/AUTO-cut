@echo off
chcp 65001 >nul
REM ============================================================
REM  AutoCut 一键打包脚本（双击运行）
REM  产物：dist\AutoCut.exe（单个 exe，无需安装 Python）
REM
REM  使用前请先装好依赖：
REM      pip install pyinstaller -r requirements.txt
REM  使用方法：把本文件拖进命令行窗口回车，或直接双击运行
REM ============================================================

REM 没装 PyInstaller 会自动装
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [1/2] 首次运行，正在安装打包工具 PyInstaller ...
    python -m pip install pyinstaller
)

echo [2/2] 正在打包，大约需要几分钟，请稍候 ...
python -m PyInstaller --noconfirm --onefile --windowed --name AutoCut main.py

if exist dist\AutoCut.exe (
    echo.
    echo ============================================
    echo  打包成功！exe 在这里：
    echo  %~dp0dist\AutoCut.exe
    echo.
    echo  提示：把 ffmpeg.exe 和 ffprobe.exe 放到
    echo  AutoCut.exe 同目录（或已加入系统 PATH），
    echo  就能直接双击使用，不需要安装 Python。
    echo ============================================
    pause
) else (
    echo.
    echo 打包失败，请把上面的报错信息发给开发者。
    pause
)
