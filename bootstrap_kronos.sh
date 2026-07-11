#!/usr/bin/env bash
# Kronos 量化分析平台一键引导（在「联网环境」运行一次即可，沙箱内同样适用）。
#
# 完成三件事：
#   ① 克隆官方推理代码（shiyu-coder/Kronos，GitHub 不通时自动走 gitclone.com 镜像）
#   ② 安装依赖（requirements.txt）
#   ③ 获取权重：默认 base（最强开源版，经 hf-mirror.com / huggingface.co 完整镜像）；
#      受限网络（仅 Gitee AI 可达）下 base 不可达，自动回退 Gitee AI 的 Kronos-small
#
# 重要：受限网络下 HF 官方 xet CDN（cas-bridge.xethub.hf.co）被防火墙拦截，
#       故不能依赖运行时 from_pretrained 联网下载。本脚本把权重落地到本地，
#       之后推理全程离线（KRONOS_LOCAL_DIR）。base 需 hf-mirror/HF 可达；
#       若仅 Gitee 可达则自动改用 small（适配器随之降级到 small，不中断流程）。
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# 解释器探测：优先 python3.11，回退 python3
PY="python3.11"; command -v "$PY" >/dev/null 2>&1 || PY="python3"

VENDOR="$ROOT/_vendor/Kronos"
WEIGHTS="$ROOT/_local_kronos_weights"

# ---------- ① 克隆官方代码 ----------
if [ ! -f "$VENDOR/model.py" ] && [ ! -d "$VENDOR/.git" ]; then
  echo "克隆 Kronos 仓库 -> $VENDOR"
  if ! git clone --depth 1 https://github.com/shiyu-coder/Kronos "$VENDOR" 2>/dev/null; then
    echo "GitHub 直连失败，尝试镜像 gitclone.com ..."
    git clone --depth 1 https://gitclone.com/github.com/shiyu-coder/Kronos "$VENDOR"
  fi
else
  echo "Kronos vendor 已存在： $VENDOR"
fi

# ---------- ② 安装依赖 ----------
if [ -f "$VENDOR/requirements.txt" ]; then
  echo "安装依赖（requirements.txt）..."
  "$PY" -m pip install -r "$VENDOR/requirements.txt"
  # 修正 requirements.txt 可能把 huggingface_hub 降级到与 transformers 5.x 不兼容的旧版（<1.3.0）。
  # Kronos 推理依赖 transformers（from_pretrained），需 huggingface_hub>=1.3.0；实测 1.4.0 可用。
  "$PY" -m pip install "huggingface_hub==1.4.0"
fi

# ---------- ③ 获取权重（默认 base；受限网络回退 small） ----------
MODEL_DIR="$WEIGHTS/NeoQuasar--Kronos-base"
MODEL_W="$MODEL_DIR/model.safetensors"
TOK_W="$WEIGHTS/NeoQuasar--Kronos-Tokenizer-base/model.safetensors"
if [ -s "$MODEL_W" ] && [ -s "$TOK_W" ]; then
  echo "base 权重已存在，跳过下载： $MODEL_DIR"
elif command -v "$PY" >/dev/null 2>&1; then
  echo "下载 Kronos-base 权重（经 hf-mirror.com）..."
  if "$PY" download_kronos_weights.py --repo NeoQuasar/Kronos-base \
        --tokenizer NeoQuasar/Kronos-Tokenizer-base --out "$WEIGHTS"; then
    echo "base 权重下载完成。"
  else
    echo "⚠️ base 经 hf-mirror 下载失败（网络受限？），回退 Gitee AI 的 Kronos-small ..."
    "$PY" fetch_kronos_weights.py --out "$WEIGHTS"
    export KRONOS_MODEL_REPO="NeoQuasar/Kronos-small"   # 与落地权重一致
    MODEL_W="$WEIGHTS/NeoQuasar--Kronos-small/model.safetensors"
  fi
else
  echo "未找到 python，跳过权重下载（请手动运行 download_kronos_weights.py）"
fi

# ---------- ④ 校验权重可加载 ----------
echo "校验权重完整性（safetensors）..."
"$PY" - <<'PY'
import os, sys
from safetensors import safe_open
w = "_local_kronos_weights"
repo = os.environ.get("KRONOS_MODEL_REPO", "NeoQuasar/Kronos-base").replace("/", "--")
for sub in [repo, "NeoQuasar--Kronos-Tokenizer-base"]:
    p = os.path.join(w, sub, "model.safetensors")
    if not os.path.exists(p):
        print(f"  [缺失] {p}")
        sys.exit(1)
    with safe_open(p, framework="pt") as f:
        n = len(f.keys())
    print(f"  [OK] {sub}: {n} tensors")
PY

echo ""
echo "=== 引导完成 ==="
echo "运行前设置环境变量："
echo "  export KRONOS_LOCAL_DIR=$WEIGHTS"
echo "  export KRONOS_REPO_PATH=$VENDOR"
echo "  export PYTHONPATH=$ROOT"
echo "然后： $PY _run_real.py"
echo ""
echo "说明：权重已离线就绪，推理全程无需联网。"
echo "若你的网络能直连 HF，可删掉 _local_kronos_weights 并设 KRONOS_HF_ENDPOINT 走镜像。"
