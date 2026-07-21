@echo off
chcp 65001 >nul 2>&1
REM ============================================================
REM A股日频量化分析平台 · 前端依赖一键安装脚本
REM 用法：在 quant-platform 根目录双击本文件
REM 作用：检查/安装 pnpm → 进入 web/ → pnpm install → 可选启动 dev
REM ============================================================
cd /d "%~dp0"
echo.
echo ========================================
echo   前端依赖安装（pnpm）
echo ========================================
echo.

REM ---------- ① 检查 Node.js ----------
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Node.js。请先安装 Node.js 22.x：
    echo        https://nodejs.org/ （选择 LTS 版本）
    echo        安装时勾选 "Add to PATH"
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('node --version') do set NODE_VER=%%v
echo [OK] Node.js %NODE_VER%

REM ---------- ② 检查/安装 pnpm ----------
where pnpm >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo pnpm 未安装，正在通过 npm 全局安装...
    npm install -g pnpm
    if %errorlevel% neq 0 (
        echo [错误] pnpm 安装失败。请手动执行：npm install -g pnpm
        pause & exit /b 1
    )
)
for /f "tokens=*" %%v in ('pnpm --version') do set PNPM_VER=%%v
echo [OK] pnpm %PNPM_VER%

REM ---------- ③ 进入 web/ 并安装 ----------
if not exist "web\package.json" (
    echo [错误] web\package.json 不存在，请确认在项目根目录运行此脚本。
    pause & exit /b 1
)
echo.
echo 正在进入 web\ 目录并安装前端依赖...
cd web

echo.
echo === pnpm install ===
call pnpm install
if %errorlevel% neq 0 (
    echo.
    echo [警告] pnpm install 可能遇到问题，尝试以下操作：
    echo   1. 运行 pnpm approve-builds esbuild（允许 esbuild 构建脚本）
    echo   2. 或删除 node_modules 和 pnpm-lock.yaml 后重试
) else (
    echo.
    echo ========================================
    echo   ✓ 前端依赖安装完成！
    echo ========================================
    echo.
    echo 现在可以启动前端开发服务器：
    echo   pnpm dev
    echo   然后浏览器打开 http://localhost:5173
    echo.
    choice /C YN /M "是否立即启动 pnpm dev？(Y/N)"
    if errorlevel 2 goto :eof
    echo.
    echo 启动中...
    call pnpm dev
)
cd ..
pause
