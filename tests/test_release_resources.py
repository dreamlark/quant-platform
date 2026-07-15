"""P3-2 资源发布单测：打包 + manifest 更新一致性（不触网，--no-upload / --dry-run）。

验证：
- build_archive：按源文件打包，只含声明成员，sha256/size 非空。
- update_manifest：版本/tag/base_url 刷新，各资源 archive/sha256/size/files 更新，结构保留。
- 端到端（--no-upload）：tar 落地 + manifest 更新 + manifest 的 sha256 与实际 tar 一致 + 解压后文件齐。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tarfile

import tools.release_resources as rr


def _seed_repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "data" / "market.duckdb").write_bytes(b"market-data")
    (root / "data" / "analytics.duckdb").write_bytes(b"analytics-data")
    (root / "_local_kronos_weights" / "sub").mkdir(parents=True)
    (root / "_local_kronos_weights" / "w.bin").write_bytes(b"weights")
    monkeypatch.setattr(rr, "REPO_ROOT", str(root))
    monkeypatch.setattr(rr, "RELEASE_DIR", str(tmp_path / "releases"))
    monkeypatch.setattr(rr, "MANIFEST", str(tmp_path / "manifest.json"))
    return root


def test_build_archive_members_and_sha(tmp_path, monkeypatch):
    root = _seed_repo(tmp_path, monkeypatch)
    out = str(tmp_path / "out")
    info = rr.build_archive("data", "2026-07-15", out)
    assert info is not None
    assert info["archive"] == "quant-platform-data-2026-07-15.tar.gz"
    assert info["sha256"]
    assert info["size_bytes"] > 0
    # tar 仅含声明的 duckdb，不含 raw_cache/无关文件
    with tarfile.open(os.path.join(out, info["archive"])) as tar:
        names = tar.getnames()
    assert "data/market.duckdb" in names
    assert "data/analytics.duckdb" in names
    assert "data/verify_snapshot.duckdb" not in names  # 不存在则不含


def test_build_archive_models(tmp_path, monkeypatch):
    root = _seed_repo(tmp_path, monkeypatch)
    out = str(tmp_path / "out")
    info = rr.build_archive("models", "2026-07-15", out)
    assert info is not None
    with tarfile.open(os.path.join(out, info["archive"])) as tar:
        names = tar.getnames()
    assert any(n.startswith("_local_kronos_weights/") for n in names)


def test_update_manifest_fields(tmp_path, monkeypatch):
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps({
        "repo_slug": "dreamlark/quant-platform",
        "resources": {"data": {"name": "旧名", "extract_to": "data"}},
    }))
    monkeypatch.setattr(rr, "MANIFEST", str(mpath))
    updates = {
        "data": {"archive": "quant-platform-data-2026-07-15.tar.gz", "sha256": "abc", "size_bytes": 10, "files": ["data/market.duckdb"]},
    }
    m = rr.update_manifest("2026-07-15", updates)
    assert m["version"] == "2026-07-15"
    assert m["tag"] == "resources-2026-07-15"
    assert m["base_url"].endswith("/resources-2026-07-15")
    d = m["resources"]["data"]
    assert d["archive"] == "quant-platform-data-2026-07-15.tar.gz"
    assert d["sha256"] == "abc"
    assert d["extract_to"] == "data"
    assert d["files"] == ["data/market.duckdb"]
    # 写盘后可读回一致
    reloaded = json.loads(mpath.read_text(encoding="utf-8"))
    assert reloaded["tag"] == "resources-2026-07-15"


def test_e2e_no_upload_consistency(tmp_path, monkeypatch, capsys):
    root = _seed_repo(tmp_path, monkeypatch)
    out = tmp_path / "releases"
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps({
        "repo_slug": "dreamlark/quant-platform",
        "resources": {"data": {"name": "数据", "extract_to": "data"}, "models": {"name": "模型", "extract_to": "."}},
    }))
    monkeypatch.setattr(rr, "RELEASE_DIR", str(out))
    monkeypatch.setattr(rr, "MANIFEST", str(mpath))

    # 模拟命令行：--all --no-upload --keep 1
    import sys
    from unittest import mock

    argv = ["release_resources.py", "--all", "--no-upload", "--keep", "1"]
    with mock.patch.object(sys, "argv", argv):
        rr.main()

    # manifest 更新，且 sha256 与实际 tar 一致
    m = json.loads(mpath.read_text(encoding="utf-8"))
    data_tar = os.path.join(str(out), m["resources"]["data"]["archive"])
    assert os.path.exists(data_tar)
    assert m["resources"]["data"]["sha256"] == rr._sha256(data_tar)
    # 解压数据 tar 后文件齐（fetch_resources --check 的契约）
    with tarfile.open(data_tar) as tar:
        tar.extractall(str(root))
    assert (root / "data" / "market.duckdb").exists()
    # 保留策略：--keep 1 → 仅 1 个 tar/资源
    data_tars = [p for p in os.listdir(str(out)) if p.startswith("quant-platform-data-")]
    assert len(data_tars) == 1
