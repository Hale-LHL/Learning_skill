#!/usr/bin/env python3
"""把 workspace 里的 study-os 开发副本同步到已安装位置 ~/.workbuddy/skills/study-os。

方向永远是 repo -> skills（单向）。想改规则请改 repo（git 可追踪），
然后跑一次本脚本；直接改安装副本的修改会在下次同步时被覆盖。

用法：python tools/sync_skills.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEST = Path.home() / ".workbuddy" / "skills" / "study-os"

SKIP_DIRS = {".git", "__pycache__", "scratch", ".workbuddy"}
SKIP_FILES = {"*.pyc"}


def sync() -> int:
    if not DEST.exists():
        print(f"[init] 创建安装目录 {DEST}")
    copied, skipped = 0, 0
    for src in REPO.rglob("*"):
        rel = src.relative_to(REPO)
        if any(part in SKIP_DIRS for part in rel.parts):
            skipped += 1
            continue
        if src.suffix == ".pyc":
            skipped += 1
            continue
        dst = DEST / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1

    # 清掉安装副本里 repo 已删除的文件，避免幽灵文件残留
    ghost = 0
    for dst in list(DEST.rglob("*")):
        rel = dst.relative_to(DEST)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if not (REPO / rel).exists() and dst.is_file():
            dst.unlink(missing_ok=True)
            ghost += 1

    print(f"[ok] 同步 {copied} 个文件，跳过 {skipped} 个，清理幽灵文件 {ghost} 个")
    print(f"     repo: {REPO}")
    print(f"     安装: {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(sync())
