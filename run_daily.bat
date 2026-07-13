@echo off
chcp 65001 >nul 2>&1
REM ============================================================
REM 每日运行包装：激活 venv -> 跑 _run_real.py（HS300 全量一轮）
REM 用法：
REM   手动：双击本文件，或 PowerShell 跑 .\run_daily.bat
REM   自动：注册到 Windows 任务计划程序（见下方命令）
REM ============================================================
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo [错误] 未找到 .venv，请先运行 deploy_windows.bat 完成部署
    pause & exit /b 1
)
call ".venv\Scripts\activate.bat"
echo [%date% %time%] 开始每日更新与预测...
python _run_real.py
echo [%date% %time%] 完成。退出码=%errorlevel%
if not defined RUN_FROM_TASK (
    pause
)
