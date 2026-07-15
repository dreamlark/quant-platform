"""资源发布编排（P3-2）：打包可选大资源 → 更新 manifest（版本+sha256）→ 上传 Release（best-effort）。

与 ``tools/fetch_resources.py`` 共用同一份 ``resources/manifest.json`` 契约，保证上下行一致，
``fetch_resources.py --check`` 对产出直接通过。

流程：
  ① 打包 ``data/``（market/analytics/verify_snapshot duckdb，排除 raw_cache 等可重生文件）
     与 ``_local_kronos_weights/`` 为两个 tar.gz；
  ② 计算 sha256 + size_bytes；
  ③ 更新 manifest：bump version(YYYY-MM-DD)/updated_at/tag/base_url，刷新各资源
     archive/sha256/size_bytes/files（保留 name/description/extract_to）；
  ④ 每个资源本地保留最近 --keep 个 tar（默认 3，data/models 独立回滚）；
  ⑤ --upload 时尝试用 ``gh`` 建/更新 Release 并上传（需 GITHUB_TOKEN；失败仅告警不阻断）。

幂等：同 version 重跑覆盖本地产物；--dry-run 仅预览不写文件。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import tarfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(REPO_ROOT, "resources", "manifest.json")
RELEASE_DIR = os.path.join(REPO_ROOT, "resources", "releases")

# 各资源：源文件/目录、解压目标、归档内成员相对路径、默认排除
RESOURCE_PLAN = {
    "data": {
        "sources": [
            os.path.join("data", "market.duckdb"),
            os.path.join("data", "analytics.duckdb"),
            os.path.join("data", "verify_snapshot.duckdb"),
        ],
        "extract_to": "data",
        "name": "数据（行情 + 分析结果）",
        "description": "market.duckdb（日线行情）、analytics.duckdb（因子/信号/回测/情绪指数等分析结果）、verify_snapshot.duckdb（验证快照）。解压到仓库 data/。",
    },
    "models": {
        "sources": [os.path.join("_local_kronos_weights")],
        "extract_to": ".",
        "name": "模型权重（离线推理）",
        "description": "Kronos 等离线模型权重（_local_kronos_weights/）。解压到仓库根目录。缺模型时预测源自动降级，不影响核心链路。",
    },
}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def build_archive(key: str, version: str, out_dir: str, dry_run: bool = False) -> dict | None:
    """打包单个资源，返回 {archive, sha256, size_bytes, files}；无源文件返回 None。"""
    plan = RESOURCE_PLAN[key]
    members: list[str] = []
    src_root = REPO_ROOT
    for src in plan["sources"]:
        full = os.path.join(src_root, src)
        if not os.path.exists(full):
            continue
        if os.path.isdir(full):
            for dirpath, _dirs, files in os.walk(full):
                for fn in files:
                    abs_p = os.path.join(dirpath, fn)
                    rel = os.path.relpath(abs_p, src_root)
                    members.append(rel)
        else:
            members.append(src)
    if not members:
        return None

    archive_name = f"quant-platform-{key}-{version}.tar.gz"
    archive_path = os.path.join(out_dir, archive_name)
    if not dry_run:
        os.makedirs(out_dir, exist_ok=True)
        with tarfile.open(archive_path, "w:gz") as tar:
            for m in members:
                tar.add(os.path.join(src_root, m), arcname=m)

    info = {
        "archive": archive_name,
        "files": members,
        "sha256": _sha256(archive_path) if not dry_run else "",
        "size_bytes": os.path.getsize(archive_path) if not dry_run else 0,
    }
    return info


def update_manifest(version: str, updates: dict, dry_run: bool = False) -> dict:
    """更新 manifest 的版本字段与各区资源字段，返回更新后的 manifest。"""
    if os.path.exists(MANIFEST):
        with open(MANIFEST, "r", encoding="utf-8") as f:
            m = json.load(f)
    else:
        m = {"resources": {}}

    tag = f"resources-{version}"
    m["version"] = version
    m["updated_at"] = dt.date.today().isoformat()
    m["tag"] = tag
    slug = m.get("repo_slug", "")
    if slug:
        m["base_url"] = f"https://github.com/{slug}/releases/download/{tag}"

    res = m.setdefault("resources", {})
    for key, info in updates.items():
        if info is None:
            continue
        block = res.get(key, {})
        block["name"] = block.get("name") or RESOURCE_PLAN[key]["name"]
        block["description"] = block.get("description") or RESOURCE_PLAN[key]["description"]
        block["extract_to"] = RESOURCE_PLAN[key]["extract_to"]
        block["archive"] = info["archive"]
        block["sha256"] = info["sha256"]
        block["size_bytes"] = info["size_bytes"]
        block["files"] = info["files"]
        res[key] = block
    m["resources"] = res

    if not dry_run:
        os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
        with open(MANIFEST, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    return m


def retain_releases(out_dir: str, keep: int) -> None:
    """每个资源保留最近 keep 个 tar（按文件名版本时间排序，便于独立回滚）。"""
    if keep <= 0 or not os.path.isdir(out_dir):
        return
    prefix = "quant-platform-"
    by_key: dict[str, list[str]] = {}
    for name in os.listdir(out_dir):
        if not (name.endswith(".tar.gz") and name.startswith(prefix)):
            continue
        # quant-platform-<key>-<version>.tar.gz → 取 <key>
        rest = name[len(prefix):-len(".tar.gz")]
        key = rest.rsplit("-", 1)[0]
        by_key.setdefault(key, []).append(name)
    for names in by_key.values():
        for old in sorted(names, reverse=True)[keep:]:
            try:
                os.remove(os.path.join(out_dir, old))
            except OSError:
                pass


def upload_via_gh(version: str, out_dir: str) -> bool:
    """best-effort：用 gh 建/更新 Release 并上传 tar（需 GITHUB_TOKEN）。失败返回 False。"""
    import shutil
    import subprocess

    if not shutil.which("gh"):
        print("⚠️  未找到 gh CLI，跳过上传（本地产物 + manifest 已就绪）。")
        return False
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("⚠️  未设置 GITHUB_TOKEN/GH_TOKEN，跳过上传。")
        return False
    tag = f"resources-{version}"
    tars = [os.path.join(out_dir, p) for p in os.listdir(out_dir) if p.endswith(".tar.gz")]
    try:
        env = dict(os.environ, GITHUB_TOKEN=token)
        # 已存在则更新，不存在则创建
        subprocess.run(
            ["gh", "release", "delete", tag, "--yes"],
            cwd=REPO_ROOT, env=env, capture_output=True,
        )
        subprocess.run(
            ["gh", "release", "create", tag, "--title", f"资源 {version}", *tars],
            cwd=REPO_ROOT, env=env, check=True,
        )
        print(f"✅ 已上传 Release {tag}（{len(tars)} 个资产）")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  上传失败（不影响本地产物）：{exc}")
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description="发布可选大资源（打包 + manifest + 上传）")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--all", action="store_true", help="数据与模型都发布")
    grp.add_argument("--data", action="store_true", help="仅数据")
    grp.add_argument("--models", action="store_true", help="仅模型")
    ap.add_argument("--dry-run", action="store_true", help="仅预览，不写文件/不上传")
    ap.add_argument("--no-upload", action="store_true", help="本地打包+更新 manifest，不触网")
    ap.add_argument("--upload", action="store_true", help="打包后尝试用 gh 上传 Release")
    ap.add_argument("--keep", type=int, default=3, help="每个资源本地保留最近 N 个 tar（默认 3）")
    ap.add_argument("--version", default=None, help="覆盖版本日期（默认今天 YYYY-MM-DD）")
    ap.add_argument("--out-dir", default=None, help="tar 输出目录（默认 resources/releases）")
    args = ap.parse_args()

    version = args.version or dt.date.today().isoformat()
    out_dir = args.out_dir or RELEASE_DIR
    keys = []
    if args.all or args.data:
        keys.append("data")
    if args.all or args.models:
        keys.append("models")

    updates = {}
    for key in keys:
        info = build_archive(key, version, out_dir, dry_run=args.dry_run)
        updates[key] = info
        if info is None:
            print(f"[skip] {key}：无源文件，跳过")
        else:
            print(f"[ok] {key}：{info['archive']} sha256={info['sha256'][:12]}… size={info['size_bytes']}")

    manifest = update_manifest(version, updates, dry_run=args.dry_run)
    print(f"\n=== manifest 已更新（version={manifest.get('version')}, tag={manifest.get('tag')}）===")

    if not args.dry_run:
        retain_releases(out_dir, args.keep)

    if args.upload and not args.dry_run:
        upload_via_gh(version, out_dir)
    elif args.dry_run:
        print("（dry-run：未写入任何文件）")
    else:
        print("（未指定 --upload：本地产物 + manifest 已就绪，手动或 CI 上传）")


if __name__ == "__main__":
    main()
