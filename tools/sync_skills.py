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

    # 清掉安装副本里 repo 已删除的文件，避免幽灵文件残留。
    # 注意：复制已经在上面完成，这一步失败**不该**让整个同步报错退出。
    # 部分 Windows 环境的 safe-delete 中间件会拦 Path.unlink 并抛
    # SAFE_DELETE_FAIL_CLOSED（而且报错说没删，其实有时已经删了），
    # 之前一次同步就是崩在这里，看起来像"同步失败"，实际文件早就过去了。
    ghost, failed = 0, []
    for dst in list(DEST.rglob("*")):
        rel = dst.relative_to(DEST)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if not (REPO / rel).exists() and dst.is_file():
            try:
                dst.unlink()
                ghost += 1
            except OSError:
                failed.append(str(rel))

    print(f"[ok] 同步 {copied} 个文件，跳过 {skipped} 个，清理幽灵文件 {ghost} 个")
    if failed:
        print(f"[warn] {len(failed)} 个残留文件删不掉（多半是 safe-delete 中间件拦的），"
              f"不影响使用，手动删即可：")
        for rel in failed:
            print(f"       rm -f \"{DEST / rel}\"")
    print(f"     repo: {REPO}")
    print(f"     安装: {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(sync())
