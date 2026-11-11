"""初始化 study-os 状态目录。

用法：
    python scripts/init.py            # 创建目录与默认 profile
    python scripts/init.py --force    # 重建 profile（不删已有卡片与错题）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

DEFAULT_PROFILE = {
    "level": None,  # novice / intermediate / advanced / None(未判定)
    "created": C.iso(C.today()),
    "graduated": [],  # 已放手的话题列表
    "illusions": [],  # 胜任错觉记录
    "notes": "",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="初始化 study-os 状态目录")
    ap.add_argument("--force", action="store_true", help="覆盖已有 profile.json")
    args = ap.parse_args()

    root = C.ensure()
    prof_file = root / "profile.json"
    if args.force or not prof_file.exists():
        C.save("profile.json", DEFAULT_PROFILE)
        print(f"[ok] profile.json 已{'重建' if args.force else '创建'}")
    else:
        print("[skip] profile.json 已存在（--force 可覆盖）")

    # 保证空文件存在，避免下游脚本反复判断
    if not (root / "cards/cards.json").exists():
        C.save_cards([])
    if not (root / "mistakes/index.json").exists():
        C.save_mistakes([])

    print(f"[ok] 状态目录：{root}")
    for d in C.SUBDIRS:
        n = len(list((root / d).glob("*")))
        print(f"     {d}/  ({n} 项)")
    print("\n下一步：python scripts/review.py due")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
