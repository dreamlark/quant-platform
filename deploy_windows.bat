@echo off
chcp 65001 >nul 2>&1
REM ============================================================
REM A股日频量化分析平台 · Windows 一键部署脚本
REM 用法：在 quant-platform 目录下双击本文件 或 PowerShell 运行：
REM   .\deploy_windows.bat
REM 前置要求：已安装 Python 3.10+、Git、Node.js (pnpm)
REM ============================================================
echo.
echo ========================================
echo   A股日频量化分析平台 · Windows 部署
echo ========================================
cd /d "%~dp0"
echo 当前目录: %cd%
echo.

REM ---------- ① 检查 Python ----------
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 python。请先安装 Python 3.10+ 并加入 PATH。
    echo        https://www.python.org/downloads/
    pause & exit /b 1
)
python --version
echo.

REM ---------- ② 检查 _vendor/Kronos（代码包应已含）----------
if exist "_vendor\Kronos\model.py" (
    echo [OK] Kronos vendor 已存在: _vendor\Kronos
) else (
    echo [提示] 克隆 Kronos 官方推理代码...
    git clone --depth 1 https://github.com/shiyu-coder/Kronos "_vendor\Kronos" 2>nul
    if %errorlevel% neq 0 (
        echo GitHub 直连失败，尝试镜像 gitclone.com ...
        git clone --depth 1 https://gitclone.com/github.com/shiyu-coder/Kronos "_vendor\Kronos"
    )
)
echo.

REM ---------- ③ 创建虚拟环境并装依赖 ----------
if not exist ".venv" (
    echo 创建 Python 虚拟环境...
    python -m venv .venv
)
call ".venv\Scripts\activate.bat"
echo [OK] 虚拟环境已激活: .venv
echo.

echo 安装项目依赖（requirements.txt）...
pip install -r requirements.txt 2>nul
echo 安装 Kronos vendor 依赖...
if exist "_vendor\Kronos\requirements.txt" (
    pip install -r "_vendor\Kronos\requirements.txt" 2>nul
)
REM huggingface_hub 兼容性修正
pip install "huggingface_hub>=1.3.0,<2.0" 2>nul
echo.

REM ---------- ④ 下载 Kronos 权重（默认 base）----------
set WEIGHTS=%~dp0_local_kronos_weights
if exist "%WEIGHTS%\NeoQuasar--Kronos-base\model.safetensors" (
    echo [OK] base 权重已存在: %WEIGHTS%
) else (
    echo.
    echo 下载 Kronos-base 权重（约 102MB，经 hf-mirror.com）...
    echo 若网络受限会自动回退 Kronos-small（约 25MB）
    echo.
    mkdir "%WEIGHTS%" 2>nul
    REM 尝试 base（hf-mirror）
    python download_kronos_weights.py --repo NeoQuasar/Kronos-base --tokenizer NeoQuasar/Kronos-Tokenizer-base --out "%WEIGHTS%"
    if %errorlevel% neq 0 (
        echo.
        echo ⚠️ base 下载失败，回退 Gitee AI 的 Kronos-small ...
        set KRONOS_MODEL_REPO=NeoQuasar/Kronos-small
        python fetch_kronos_weights.py --out "%WEIGHTS%"
    )
)

REM ---------- ⑤ 校验权重 ----------
echo.
echo 校验权重完整性...
python -c "import os; from safetensors import safe_open; w='_local_kronos_weights'; repo=os.environ.get('KRONOS_MODEL_REPO','NeoQuasar/Kronos-base').replace('/','--'); [print(f'  [OK] {s}: {len(list(safe_open(os.path.join(w,s,\"model.safetensors\")).keys()))} tensors') for s in [repo,'NeoQuasar--Kronos-Tokenizer-base']] if os.path.exists(os.path.join(w,s,'model.safetensors')) or print(f'  [缺失] {s}')]"
echo.

REM ---------- ⑥ 设置环境变量（持久到本次 session）----------
set KRONOS_LOCAL_DIR=%WEIGHTS%
set KRONOS_REPO_PATH=%~dp0_vendor\Kronos
set PYTHONPATH=%~dp0
echo 环境变量已设置：
echo   KRONOS_LOCAL_DIR=%KRONOS_LOCAL_DIR%
echo   KRONOS_REPO_PATH=%KRONOS_REPO_PATH%
echo.

REM ---------- ⑦ 前端准备（可选）----------
where pnpm >nul 2>&1
if %errorlevel% neq 0 (
    echo pnpm 未安装，正在通过 npm 全局安装...
    npm install -g pnpm
    if %errorlevel% neq 0 (
        echo [警告] pnpm 自动安装失败，前端需手动安装
        echo        手动步骤：npm install -g pnpm ^&^& cd web ^&^& pnpm install ^&^& pnpm dev
        goto :after_frontend
    )
)
if exist "web" (
    echo 安装前端依赖（web\ 目录）...
    cd web
    call pnpm install
    if %errorlevel% neq 0 (
        echo [警告] pnpm install 可能需要运行：pnpm approve-builds esbuild
    ) else (
        echo [OK] 前端依赖安装完成
    )
    cd ..
) else (
    echo [跳过] web\ 目录不存在
)
:after_frontend
echo.

echo ========================================
echo   ✓ 部署完成！
echo ========================================
echo.
echo 接下来可以运行：
echo.
echo   启动后端 API（当前窗口）：
echo     python -m api.main
echo     或 uvicorn api.main:app --host 127.0.0.1 --port 8000
echo.
echo   启动前端（另开一个终端）：
echo     cd web && pnpm dev
echo     然后浏览器打开 http://localhost:5173
echo.
echo   运行完整预测管线：
echo     python _run_real.py
echo.
pause
