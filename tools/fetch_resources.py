#!/usr/bin/env python3
"""可选资源拉取工具（纯标准库，无第三方依赖）。

从 GitHub Release 拉取大资源（数据 / 模型），带 sha256 校验，解压到仓库对应目录。
目标：避免每位用户 clone 后本地全量重拉 akshare 行情导致 API 限流报错。

本仓库为私有仓库：匿名公开下载地址会 404。协作者请设置 GITHUB_TOKEN（或 GH_TOKEN）
环境变量后运行，脚本自动走鉴权 API 下载；也可 `export GITHUB_TOKEN=$(gh auth token)`。
若仓库日后改为公开，则无需 token，直接用公开地址。

用法:
    GITHUB_TOKEN=xxx python tools/fetch_resources.py --all
    python tools/fetch_resources.py --data          # 仅数据（需仓库公开或无 token 时失败会提示）
    python tools/fetch_resources.py --models        # 仅模型
    python tools/fetch_resources.py --check          # 仅校验已存在文件，不下载
    python tools/fetch_resources.py --all --force    # 强制覆盖已存在文件
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(REPO_ROOT, "resources", "manifest.json")


def _load_manifest() -> dict:
    if not os.path.exists(MANIFEST):
        sys.exit(f"❌ 未找到资源清单：{MANIFEST}")
    with open(MANIFEST, "r", encoding="utf-8") as f:
        return json.load(f)


def _token() -> "str | None":
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _api_asset_url(slug: str, tag: str, archive: str, token: str) -> str:
    """通过鉴权 API 解析附件的真实下载地址（私有仓库必需）。"""
    url = f"https://api.github.com/repos/{slug}/releases/tags/{tag}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "quant-platform-fetch",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        rel = json.load(resp)
    for a in rel.get("assets", []):
        if a["name"] == archive:
            return a["url"]
    raise RuntimeError(f"Release 中未找到附件 {archive}")


def _download(url: str, dest: str, label: str, token: str = None, api: bool = False) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"⬇️  下载 {label}: {url}")
    headers = {"User-Agent": "quant-platform-fetch"}
    if token and api:
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/octet-stream"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
            total = int(resp.headers.get("content-length", 0) or 0)
            got = 0
            while True:
                buf = resp.read(1 << 20)
                if not buf:
                    break
                out.write(buf)
                got += len(buf)
                if total:
                    pct = got * 100 // total
                    sys.stdout.write(f"\r   {pct:3d}%  {got/(1<<20):.1f}/{total/(1<<20):.1f} MB")
                    sys.stdout.flush()
        print()
    except urllib.error.HTTPError as e:
        # 清理半成品
        if os.path.exists(dest):
            os.remove(dest)
        if e.code in (401, 403, 404) and not (token and api):
            raise RuntimeError(
                "公开下载失败(401/403/404)。本仓库为私有：请设置 GITHUB_TOKEN 后重试，"
                "例如 `GITHUB_TOKEN=xxx python tools/fetch_resources.py --all`"
            ) from e
        raise


def _already_ok(res: dict, extract_to: str) -> bool:
    for rel in res["files"]:
        p = os.path.join(REPO_ROOT, extract_to, rel)
        if not os.path.exists(p):
            return False
    return True


def _verify_and_extract(archive: str, res: dict, force: bool) -> bool:
    print(f"🔍 校验 sha256: {os.path.basename(archive)}")
    actual = _sha256(archive)
    if actual.lower() != res["sha256"].lower():
        print(f"❌ sha256 不匹配！\n   期望 {res['sha256']}\n   实际 {actual}")
        return False
    print("✅ sha256 一致")

    dest_dir = os.path.join(REPO_ROOT, res["extract_to"])
    print(f"📦 解压到 {dest_dir}")
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest_dir)
    print(f"✅ {res['name']} 就绪")
    return True


def _fetch_one(key: str, res: dict, m: dict, token: str, force: bool) -> bool:
    print(f"\n=== {res['name']} ===")
    if not force and _already_ok(res, res["extract_to"]):
        print("✅ 文件已存在且完整，跳过（--force 可覆盖）")
        return True

    base_url = m.get("base_url", "")
    archive = res["archive"]
    if token:
        # 私有仓库：走鉴权 API 下载
        slug = m.get("repo_slug", "")
        tag = m.get("tag", "")
        url = _api_asset_url(slug, tag, archive, token)
        _download(url, os.path.join(REPO_ROOT, ".cache", archive), res["name"], token=token, api=True)
    else:
        # 公开仓库：直接用公开地址
        _download(f"{base_url}/{archive}", os.path.join(REPO_ROOT, ".cache", archive), res["name"])

    tmp = os.path.join(REPO_ROOT, ".cache", archive)
    ok = _verify_and_extract(tmp, res, force)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return ok


def _check(res: dict) -> None:
    ok = _already_ok(res, res["extract_to"])
    print(f"[{'✅' if ok else '❌'}] {res['name']}: {'完整' if ok else '缺失/不完整'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="拉取可选大资源（数据/模型）")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--all", action="store_true", help="数据与模型都拉")
    grp.add_argument("--data", action="store_true", help="仅数据")
    grp.add_argument("--models", action="store_true", help="仅模型")
    grp.add_argument("--check", action="store_true", help="仅校验已存在文件")
    ap.add_argument("--force", action="store_true", help="强制覆盖已存在文件")
    args = ap.parse_args()

    m = _load_manifest()
    res = m["resources"]
    token = _token()

    if args.check:
        for k in ("data", "models"):
            _check(res[k])
        return

    if not token and not m.get("base_url", "").startswith("https://github.com"):
        # base_url 可能是公开可访问的自定义地址
        pass

    selected = []
    if args.all or args.data:
        selected.append("data")
    if args.all or args.models:
        selected.append("models")

    if not token:
        print("⚠️  未检测到 GITHUB_TOKEN/GH_TOKEN。若下载 401/403/404，请设置 token 后重试"
              "（本仓库为私有）。\n")

    all_ok = True
    for k in selected:
        all_ok &= _fetch_one(k, res[k], m, token, args.force)

    print("\n=== 完成 ===")
    if all_ok:
        print("✅ 所选资源已就绪。直接运行 python -m uvicorn api.main:app 即可。")
    else:
        print("❌ 部分资源拉取失败，请检查网络或 GITHUB_TOKEN。")
        sys.exit(1)


if __name__ == "__main__":
    main()
