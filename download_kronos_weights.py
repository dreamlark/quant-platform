#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kronos 权重离线搬运工具（受限网络 / 沙箱环境的兜底方案）。

适用场景：
  你的「运行环境」出网被拦（拉不到 HF 的 xet CDN），但你有另一台能出网的机器
  （家用机、云主机、挂了代理的机器）。在「能出网」那台上跑本脚本，把整仓权重
  快照下载到本地目录，再把这个目录整体拷到运行环境，运行环境用 local_files_only
  加载即可，无需再联网。

用法：
  1) 在能出网的机器上：
       pip install -U "huggingface_hub[cli]"
       export HF_ENDPOINT=https://hf-mirror.com        # 国内用镜像更快
       # 如需代理：export HTTPS_PROXY=http://127.0.0.1:7890
       # 默认拉 base（平台默认模型）；如需小模型加 --repo NeoQuasar/Kronos-small
       python download_kronos_weights.py --repo NeoQuasar/Kronos-base \
              --tokenizer NeoQuasar/Kronos-Tokenizer-base \
              --out ./kronos_weights

  2) 把 ./kronos_weights 整个目录拷到运行环境（U盘 / scp / 网盘均可）。

  3) 运行环境（无需联网）设置：
       export KRONOS_LOCAL_DIR=/path/to/kronos_weights
       # 适配器会优先用 local_files_only 从该目录加载
"""
from __future__ import annotations

import argparse
import os
import sys


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="下载 Kronos 权重到本地目录（离线搬运）")
    p.add_argument(
        "--repo",
        default=os.environ.get("KRONOS_MODEL_REPO", "NeoQuasar/Kronos-base"),
        help="模型仓库 id（默认 NeoQuasar/Kronos-base；可选 -small / -mini）",
    )
    p.add_argument(
        "--tokenizer",
        default=os.environ.get("KRONOS_TOKENIZER_REPO", "NeoQuasar/Kronos-Tokenizer-base"),
        help="分词器仓库 id（默认 NeoQuasar/Kronos-Tokenizer-base）",
    )
    p.add_argument(
        "--out",
        default=os.environ.get("KRONOS_LOCAL_DIR", "./kronos_weights"),
        help="本地下载目录（拷到运行环境后设为 KRONOS_LOCAL_DIR）",
    )
    p.add_argument(
        "--endpoint",
        default=os.environ.get("HF_ENDPOINT", "https://hf-mirror.com"),
        help="HF 镜像端点（默认 hf-mirror.com；官方用 https://huggingface.co）",
    )
    return p.parse_args()


def _download_one(repo_id: str, out_root: str, endpoint: str) -> str:
    """用 huggingface_hub 快照下载单个仓库，返回本地目录路径。"""
    os.environ["HF_ENDPOINT"] = endpoint
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        sys.exit("缺少 huggingface_hub，请先: pip install -U 'huggingface_hub[cli]'")

    local_dir = os.path.join(out_root, repo_id.replace("/", "--"))
    print(f"[下载] {repo_id}  ->  {local_dir}  (endpoint={endpoint})")
    path = snapshot_download(
        repo_id=repo_id,
        local_dir=local_dir,
        local_dir_use_symlinks=False,  # 拷目录时更稳妥，避免软链断裂
    )
    print(f"[完成] {repo_id} 位于 {path}")
    return path


def main() -> None:
    args = _parse_args()
    os.makedirs(args.out, exist_ok=True)
    model_dir = _download_one(args.repo, args.out, args.endpoint)
    tok_dir = _download_one(args.tokenizer, args.out, args.endpoint)

    print("\n=== 下一步（在运行环境，无需联网）===")
    print(f"  export KRONOS_LOCAL_DIR={os.path.abspath(args.out)}")
    print(f"  export KRONOS_MODEL_REPO={args.repo}")
    print(f"  export KRONOS_TOKENIZER_REPO={args.tokenizer}")
    print("  适配器检测到 KRONOS_LOCAL_DIR 后会用 local_files_only 从该目录加载。")
    print(f"\n模型目录: {model_dir}")
    print(f"分词器目录: {tok_dir}")


if __name__ == "__main__":
    main()
