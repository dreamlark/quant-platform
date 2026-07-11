#!/usr/bin/env bash
# Kronos 量化分析平台一键引导（在「联网环境」运行一次即可，沙箱内同样适用）。
#
# 完成三件事：
#   ① 克隆官方推理代码（shiyu-coder/Kronos，GitHub 不通时自动走 gitclone.com 镜像）
#   ② 安装依赖（requirements.txt）
#   ③ 双源获取权重（绕过 HF xet CDN）：模型走 Gitee AI，分词器走 GitCode AI
#
# 重要：受限网络下 HF 官方 xet CDN（cas-bridge.xethub.hf.co）被防火墙拦截，
#       故不能依赖运行时 from_pretrained 联网下载。本脚本用已验证可用的双源
#       把权重落地到本地，之后推理全程离线（KRONOS_LOCAL_DIR）。
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

# ---------- ③ 双源获取权重（绕过 xet CDN） ----------
MODEL_W="$WEIGHTS/NeoQuasar--Kronos-small/model.safetensors"
TOK_W="$WEIGHTS/NeoQuasar--Kronos-Tokenizer-base/model.safetensors"
if [ -s "$MODEL_W" ] && [ -s "$TOK_W" ]; then
  echo "权重已存在，跳过下载： $WEIGHTS"
else
  echo "双源获取 Kronos 权重（Gitee AI 模型 + GitCode AI 分词器）..."
  "$PY" fetch_kronos_weights.py --out "$WEIGHTS"
fi

# ---------- ④ 校验权重可加载 ----------
echo "校验权重完整性（safetensors）..."
"$PY" - <<'PY'
import os, sys
from safetensors import safe_open
w = "_local_kronos_weights"
for sub in ["NeoQuasar--Kronos-small", "NeoQuasar--Kronos-Tokenizer-base"]:
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
