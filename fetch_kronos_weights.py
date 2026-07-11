#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kronos 权重双源获取脚本 —— **Kronos-small 专用**（绕过 HF xet CDN，仅 Gitee AI 可达时）。

⚠️ 平台默认模型已切换为 **Kronos-base**（最强开源版）。base / mini / large 在 Gitee AI
**未镜像**（404），无法用本脚本下载。本脚本仅用于「网络受限、只有 Gitee AI 可达」时
获取 **small** 权重作为兜底。要获取 base，请改用 ``download_kronos_weights.py``（hf-mirror）。

为什么需要双源（仅 small）？
  Kronos 推理必须同时有「模型权重」+「分词器权重」。各国内镜像站覆盖不完整：
    - Gitee AI (hf-api.gitee.com) 有模型权重（NeoQuasar/Kronos-small），可 curl 直连，
      是唯一实测能绕过 HF xet CDN 拉到 model.safetensors 的渠道；
    - Gitee AI 不含分词器；分词器在 GitCode AI (gitcode.com) 可匿名 git clone。
  故采用：模型走 Gitee AI，分词器走 GitCode AI。

输出目录结构（可直接设为 KRONOS_LOCAL_DIR）：
  <out>/
    NeoQuasar--Kronos-small/          config.json, model.safetensors, README.md
    NeoQuasar--Kronos-Tokenizer-base/ config.json, model.safetensors, README.md

用法（small 兜底）：
  python fetch_kronos_weights.py --out ./kronos_weights
  export KRONOS_LOCAL_DIR=$(pwd)/kronos_weights
  export KRONOS_MODEL_REPO=NeoQuasar/Kronos-small   # 与落地权重一致
  # 之后 KronosAdapter 会用 local_files_only 从本地加载，无需联网

默认 base 的离线获取（推荐）：
  python download_kronos_weights.py --repo NeoQuasar/Kronos-base --out ./kronos_weights
  export KRONOS_LOCAL_DIR=$(pwd)/kronos_weights
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# ---------- 配置 ----------
GITEE_MODEL_REPO = "NeoQuasar/Kronos-small"
GITEE_MODEL_FILES = ["config.json", "model.safetensors", "README.md"]
GITEE_MODEL_BASE = f"https://hf-api.gitee.com/{GITEE_MODEL_REPO}/resolve/main"

GITCODE_TOK_REPO = "https://gitcode.com/hf_mirrors/NeoQuasar/Kronos-Tokenizer-base.git"
GITCODE_TOK_FILES = ["config.json", "model.safetensors", "README.md"]


def _run(cmd: list[str]) -> None:
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def fetch_model(out_root: str) -> None:
    base = os.path.join(out_root, "NeoQuasar--Kronos-small")
    os.makedirs(base, exist_ok=True)
    for fn in GITEE_MODEL_FILES:
        url = f"{GITEE_MODEL_BASE}/{fn}"
        dst = os.path.join(base, fn)
        print(f"[模型] {fn} <- {url}")
        _run(["curl", "-sL", "--max-time", "600", "-o", dst, url])
        if os.path.getsize(dst) < 100:
            sys.exit(f"模型文件 {fn} 下载异常（过小），请检查网络/Gitee AI 可用性")


def fetch_tokenizer(out_root: str) -> None:
    base = os.path.join(out_root, "NeoQuasar--Kronos-Tokenizer-base")
    os.makedirs(base, exist_ok=True)
    tmp = os.path.join(out_root, "_tok_clone_tmp")
    if os.path.exists(tmp):
        _run(["rm", "-rf", tmp])
    print(f"[分词器] git clone {GITCODE_TOK_REPO}")
    _run(["git", "clone", "--depth", "1", GITCODE_TOK_REPO, tmp])
    for fn in GITCODE_TOK_FILES:
        src = os.path.join(tmp, fn)
        if os.path.exists(src):
            _run(["cp", src, os.path.join(base, fn)])
        else:
            print(f"  [警告] 分词器缺文件 {fn}")
    _run(["rm", "-rf", tmp])


def main() -> None:
    ap = argparse.ArgumentParser(description="Kronos 权重双源获取（绕过 xet CDN）")
    ap.add_argument("--out", default="./kronos_weights", help="输出目录（设为 KRONOS_LOCAL_DIR）")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    fetch_model(args.out)
    fetch_tokenizer(args.out)

    abs_path = os.path.abspath(args.out)
    print("\n=== 完成 ===")
    print(f"权重已就绪：{abs_path}")
    print(f"运行环境设置：export KRONOS_LOCAL_DIR={abs_path}")
    print("（适配器会用 local_files_only 从本地加载，无需联网）")


if __name__ == "__main__":
    main()
