"""检索卡 + SM-2 间隔调度。

用法：
    python scripts/review.py due [-n 5]         # 今天到期的卡
    python scripts/review.py add -q "问题" -a "答案" [-t 标签] [--interval 1]
    python scripts/review.py grade --id <id> --q 4
    python scripts/review.py list [--tag 标签]
    python scripts/review.py stats
    python scripts/review.py postpone --id <id> --days 1

评分 q（0-5）：
    0 完全想不起   1 眼熟但说不出   2 想起一半且错
    3 勉强答对     4 答对略慢       5 秒答且完整
    <3 视为失败：重置进度，明天再来
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# SM-2 初版 easiness factor
DEFAULT_EF = 2.5
MIN_EF = 1.3


def sm2_update(card: dict, q: int) -> dict:
    """标准 SM-2 更新。q 为 0-5 的回忆质量。"""
    ef = float(card.get("ef", DEFAULT_EF))
    rep = int(card.get("rep", 0))
    interval = int(card.get("interval", 0))

    if q < 3:
        rep = 0
        interval = 1
    else:
        if rep == 0:
            interval = 1
        elif rep == 1:
            interval = 6
        else:
            interval = max(1, round(interval * ef))
        rep += 1

    ef = ef + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    ef = max(MIN_EF, round(ef, 3))

    card["ef"] = ef
    card["rep"] = rep
    card["interval"] = interval
    card["due"] = C.iso(C.add_days(C.today(), interval))
    card["last"] = C.iso(C.today())
    card.setdefault("history", []).append({"date": C.iso(C.today()), "q": q})
    return card


def cmd_due(args) -> int:
    cards = C.load_cards()
    t = C.today()
    due = [c for c in cards if (C.as_date(c.get("due")) or date.max) <= t]
    due.sort(key=lambda c: C.as_date(c.get("due")) or date.max)
    if not due:
        print(f"今天没有到期卡片（共 {len(cards)} 张在库）")
        return 0
    limit = args.n or len(due)
    print(f"到期 {len(due)} 张，先来 {min(limit, len(due))} 张：\n")
    for i, c in enumerate(due[:limit], 1):
        tag = f"[{c['tag']}] " if c.get("tag") else ""
        print(f"{i}. {tag}{c['q']}")
        print(f"   id={c['id']}  {C.fmt_due(c)}  rep={c.get('rep', 0)}")
        print(f"   <先自己答，再看答案> 答完用 grade 记录\n")
    return 0


def cmd_add(args) -> int:
    cards = C.load_cards()
    cid = C.next_id("c", cards)
    interval = args.interval if args.interval is not None else 1
    card = {
        "id": cid,
        "q": args.q,
        "a": args.a,
        "tag": args.tag or "",
        "ef": DEFAULT_EF,
        "rep": 0,
        "interval": interval,
        "due": C.iso(C.add_days(C.today(), interval)),
        "created": C.iso(C.today()),
        "history": [],
    }
    cards.append(card)
    C.save_cards(cards)
    print(f"[ok] 已加卡 {cid}，{interval} 天后复习")
    print(f"     问题：{args.q}")
    return 0


def cmd_grade(args) -> int:
    if not 0 <= args.q <= 5:
        print("[err] q 必须在 0-5 之间", file=sys.stderr)
        return 2
    cards = C.load_cards()
    for c in cards:
        if c["id"] == args.id:
            before = dict(c)
            sm2_update(c, args.q)
            C.save_cards(cards)
            C.log_event("grade", {"id": c["id"], "q": args.q, "interval": c["interval"]})
            print(f"[ok] {c['id']} 评分 {args.q}")
            print(f"     EF {before.get('ef')} → {c['ef']}   rep {before.get('rep')} → {c['rep']}")
            print(f"     下次复习：{c['due']}（{c['interval']} 天后）")
            if args.q < 3:
                print("     ⚠ 未通过，进度重置。这题明天再来一次。")
            return 0
    print(f"[err] 找不到卡 {args.id}", file=sys.stderr)
    return 1


def cmd_list(args) -> int:
    cards = C.load_cards()
    if args.tag:
        cards = [c for c in cards if c.get("tag") == args.tag]
    if not cards:
        print("没有卡片。用 add 添加，或走错题工作流自动生成。")
        return 0
    print(C.pad("id", 20) + C.pad("tag", 14) + C.pad("rep", 5) + C.pad("EF", 7) + C.pad("due", 13) + "问题")
    for c in sorted(cards, key=lambda x: x.get("due") or ""):
        print(
            C.pad(c["id"], 20)
            + C.pad(c.get("tag") or "-", 14)
            + C.pad(c.get("rep", 0), 5)
            + C.pad(c.get("ef", 0), 7)
            + C.pad(c.get("due") or "-", 13)
            + c["q"][:40]
        )
    return 0


def cmd_postpone(args) -> int:
    cards = C.load_cards()
    for c in cards:
        if c["id"] == args.id:
            base = C.as_date(c.get("due")) or C.today()
            c["due"] = C.iso(C.add_days(max(base, C.today()), args.days))
            C.save_cards(cards)
            print(f"[ok] {c['id']} 推迟到 {c['due']}")
            return 0
    print(f"[err] 找不到卡 {args.id}", file=sys.stderr)
    return 1


def cmd_stats(args) -> int:
    cards = C.load_cards()
    if not cards:
        print("库是空的。")
        return 0
    t = C.today()
    due = sum(1 for c in cards if (C.as_date(c.get("due")) or date.max) <= t)
    leech = [c for c in cards if int(c.get("rep", 0)) == 0 and len(c.get("history", [])) >= 3]
    graded = [h for c in cards for h in c.get("history", [])]
    avg_q = sum(h["q"] for h in graded) / len(graded) if graded else 0

    print(f"卡片总数：{len(cards)}    今天到期：{due}    已评分次数：{len(graded)}")
    if graded:
        print(f"平均回忆质量：{avg_q:.2f} / 5")
    tags: dict[str, int] = {}
    for c in cards:
        tags[c.get("tag") or "(无标签)"] = tags.get(c.get("tag") or "(无标签)", 0) + 1
    print("\n按标签：")
    for k, v in sorted(tags.items(), key=lambda x: -x[1]):
        print(f"  {k:<16} {'█' * min(v, 30)} {v}")
    if leech:
        print(f"\n⚠ 疑难卡（连挂 3 次以上）：{len(leech)} 张")
        for c in leech[:5]:
            print(f"   {c['id']}  {c['q'][:40]}")
        print("   建议：拆成更小的卡，或者这篇材料本身没学透，回去重读。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="study-os 检索卡调度")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("due", help="列今天到期")
    p.add_argument("-n", type=int, default=0)
    p.set_defaults(func=cmd_due)

    p = sub.add_parser("add", help="加卡")
    p.add_argument("-q", required=True, help="问题（写成会触发回忆的形式）")
    p.add_argument("-a", required=True, help="答案")
    p.add_argument("-t", "--tag", default="")
    p.add_argument("--interval", type=int, default=None)
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("grade", help="评分（0-5）")
    p.add_argument("--id", required=True)
    p.add_argument("--q", type=int, required=True)
    p.set_defaults(func=cmd_grade)

    p = sub.add_parser("list", help="列全部")
    p.add_argument("--tag")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("postpone", help="推迟")
    p.add_argument("--id", required=True)
    p.add_argument("--days", type=int, default=1)
    p.set_defaults(func=cmd_postpone)

    p = sub.add_parser("stats", help="统计")
    p.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    C.ensure()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
