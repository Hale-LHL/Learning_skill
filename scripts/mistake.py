"""错题库：归因、查询、错误画像。

用法：
    # 交互式录入
    python scripts/mistake.py add

    # 参数化录入（agent 调用走这条）
    python scripts/mistake.py add --topic "线代/特征值" --question "求A的特征值" \\
        --mywork "我直接用行列式=0" --cause M --subcause P

    python scripts/mistake.py list [--due] [--cause M]
    python scripts/mistake.py show --id M-20261111-001
    python scripts/mistake.py retest --id <id> --pass
    python scripts/mistake.py stats

错因代号：
    K 知识缺口   M 概念误解   P 程序错误   R 表征错误
    C 粗心       T 迁移失败   E 元认知
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 代号: (名称, 首次间隔天数, 补漏方式)
CAUSES = {
    "K": ("知识缺口", 1, "回到知识点本身：最小示范 → 复述 → 一道基础题"),
    "M": ("概念误解", 2, "先破后立：让他讲出错误模型 → 构造荒谬推论 → 自己发现矛盾 → 再重建"),
    "P": ("程序错误", 1, "拆步骤定位崩点，只重练崩的那一步 3 遍，不重做整题"),
    "R": ("表征错误", 3, "条件圈画训练：每题先列全部限制条件再动笔"),
    "C": ("粗心", 7, "加检查流程（验算项/单位核对/极端值代入），不加题量"),
    "T": ("迁移失败", 4, "3 道表面不同结构相同的题，追问共同结构"),
    "E": ("元认知", 7, "自评-实测对账：先自评把握度，再闭卷做，对比差距"),
}


def prompt(label: str, default: str = "") -> str:
    try:
        v = input(f"{label}{f' [{default}]' if default else ''}: ").strip()
    except EOFError:
        v = ""
    return v or default


def cmd_add(args) -> int:
    items = C.load_mistakes()

    # 关键：--question 与 --cause 同时给出即视为批处理模式，绝不进 input()。
    # 否则在 agent / 管道环境里 input() 会阻塞或读到 EOF，行为诡异。
    batch = bool(args.question and args.cause)

    if batch:
        topic = args.topic or "(未填)"
        question = args.question
        mywork = args.mywork or "(未填)"
        cause = args.cause.upper()
        sub = (args.subcause or "").upper()
    else:
        topic = args.topic or prompt("考点（如 线代/特征值）")
        question = args.question or prompt("题目（简述即可）")
        mywork = args.mywork or prompt("你的原始解法/思路（关键，别省）")
        cause = (args.cause or prompt("主因代号 K/M/P/R/C/T/E")).upper()
        sub = (args.subcause or prompt("次因代号（可空，直接回车跳过）", "")).upper()

    if cause not in CAUSES:
        print(f"[err] 错因必须是 {'/'.join(CAUSES)} 之一", file=sys.stderr)
        return 2
    if sub and sub not in CAUSES:
        sub = ""

    name, interval, fix = CAUSES[cause]
    mid = C.next_id("M", items)
    rec = {
        "id": mid,
        "topic": topic,
        "question": question,
        "my_work": mywork,
        "cause": cause,
        "subcause": sub,
        "created": C.iso(C.today()),
        "next_due": C.iso(C.add_days(C.today(), interval)),
        "retest": {"date": None, "passed": None},
        "cards": [],
    }
    items.append(rec)
    C.save_mistakes(items)
    C.log_event("mistake_add", {"id": mid, "cause": cause})

    print(f"\n[ok] 已入库 {mid}")
    print(f"     主因：{cause} {name}（{interval} 天后回访）")
    if sub:
        print(f"     次因：{sub} {CAUSES[sub][0]}")
    print(f"\n     补漏动作 → {fix}")
    print(f"\n     下一步不是重做原题，而是做变式：改数字/改情境/反向问。")
    print(f"     成卡：python scripts/review.py add -q '...' -a '...' --interval {interval}")
    return 0


def cmd_list(args) -> int:
    items = C.load_mistakes()
    if args.cause:
        items = [i for i in items if i["cause"] == args.cause.upper()]
    if args.due:
        t = C.today()
        items = [i for i in items if (C.as_date(i.get("next_due")) or date.max) <= t]
    if not items:
        print("没有符合条件的错题。")
        return 0
    print(C.pad("id", 18) + C.pad("主因", 6) + C.pad("考点", 20) + C.pad("回访", 14) + "题目")
    for i in sorted(items, key=lambda x: x.get("next_due") or ""):
        print(
            C.pad(i["id"], 18)
            + C.pad(i["cause"], 6)
            + C.pad(i["topic"], 20)
            + C.pad(i.get("next_due") or "-", 14)
            + i["question"][:30]
        )
    return 0


def cmd_show(args) -> int:
    for i in C.load_mistakes():
        if i["id"] == args.id:
            name, _, fix = CAUSES[i["cause"]]
            print(f"{i['id']}  [{i['cause']} {name}]  {i['topic']}")
            print(f"录入：{i['created']}    回访：{i.get('next_due')}")
            print(f"\n题目：{i['question']}")
            print(f"原始思路：{i['my_work']}")
            if i.get("subcause"):
                print(f"次因：{i['subcause']} {CAUSES[i['subcause']][0]}")
            print(f"\n补漏：{fix}")
            print(f"验证：{i['retest']}")
            return 0
    print(f"[err] 找不到 {args.id}", file=sys.stderr)
    return 1


def cmd_retest(args) -> int:
    items = C.load_mistakes()
    for i in items:
        if i["id"] == args.id:
            passed = bool(args.passed)
            i["retest"] = {"date": C.iso(C.today()), "passed": passed}
            # 变式通过 → 拉长间隔；未通过 → 归因可能错了，缩短
            base = C.as_date(i.get("next_due")) or C.today()
            step = 7 if passed else 1
            i["next_due"] = C.iso(C.add_days(max(base, C.today()), step))
            C.save_mistakes(items)
            C.log_event("mistake_retest", {"id": i["id"], "passed": passed})
            if passed:
                print(f"[ok] {i['id']} 变式通过，下次回访 {i['next_due']}")
            else:
                print(f"[!] {i['id']} 变式未过 → **归因可能是错的**")
                print("    最常见：把概念误解(M)判成了程序错误(P)。回去按 M 类重走一遍。")
                print(f"    已排明天再访：{i['next_due']}")
            return 0
    print(f"[err] 找不到 {args.id}", file=sys.stderr)
    return 1


def cmd_stats(args) -> int:
    items = C.load_mistakes()
    if not items:
        print("错题库是空的。先 add 一条。")
        return 0

    total = len(items)
    recent = [
        i for i in items
        if (C.today() - (C.as_date(i.get("created")) or C.today())).days <= 30
    ]
    print(f"总错题：{total}    近 30 天：{len(recent)}\n")

    cnt = Counter(i["cause"] for i in items)
    print("错因分布：")
    for k, v in cnt.most_common():
        pct = v / total * 100
        bar = "█" * max(1, round(pct / 3))
        print(f"  {k} {C.pad(CAUSES[k][0], 10)}{C.pad(bar, 36)}{v:>3}  ({pct:.0f}%)")

    zero = [k for k in CAUSES if k not in cnt]
    if zero:
        print(f"  未出现：{', '.join(f'{k} {CAUSES[k][0]}' for k in zero)}")

    print("\n行动建议：")
    top, topn = cnt.most_common(1)[0]
    advice = {
        "M": "概念误解占首位 → 你的问题不是练得少，是理解有系统偏差。**去重读教材/看推导，不要刷题**（刷题会固化错误）。",
        "C": "粗心占首位 → **加检查流程，不加题量**。看这些错题是否集中在某个环节（单位/符号/抄写）。",
        "K": "知识缺口占首位 → 是学习进度问题，不是方法问题。正常推进即可。",
        "R": "表征错误占首位 → **训练条件圈画**。你不是不会，是没看见。",
        "T": "迁移失败占首位 → 你练的都是同型题。**换变式，别刷同类**。",
        "P": "程序错误占首位 → 步骤拆解训练。定位崩的那一步单独重练。",
        "E": "元认知问题占首位 → **每次自评把握度再对答案**，记录差距。",
    }
    ties = [k for k, v in cnt.items() if v == topn]
    if total < 5:
        print(f"  （样本仅 {total} 条，分布还不稳定。至少录到 5 条再看结论，否则容易归错方向。）")
    elif len(ties) > 1:
        print(f"  并列首位：{' / '.join(f'{k} {CAUSES[k][0]}' for k in ties)}——先分辨哪一种更常见再定策略。")
    else:
        print(f"  ★ {advice[top]}")

    # 找集中环节（同一 topic 反复错）
    topics = Counter(i["topic"].split("/")[0] for i in items)
    hot = [(t, n) for t, n in topics.most_common(3) if n >= 3]
    if hot:
        print(f"\n  反复出错的知识块：")
        for t, n in hot:
            print(f"    {t}  {n} 次 → 这块整体没过关，不是单点问题")

    passed = [i for i in items if i["retest"].get("passed") is True]
    failed = [i for i in items if i["retest"].get("passed") is False]
    if passed or failed:
        rate = len(passed) / (len(passed) + len(failed)) * 100
        print(f"\n  变式验证：通过 {len(passed)} / 未过 {len(failed)}（通过率 {rate:.0f}%）")
        if rate < 50:
            print("  ⚠ 通过率低于 50%：说明「补漏」这一步没做到位，或者归因错了。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="study-os 错题库")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="录入错题")
    p.add_argument("--topic", default="")
    p.add_argument("--question", default="")
    p.add_argument("--mywork", default="")
    p.add_argument("--cause", default="")
    p.add_argument("--subcause", default="")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="列出")
    p.add_argument("--due", action="store_true")
    p.add_argument("--cause")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="看详情")
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("retest", help="记录变式验证结果")
    p.add_argument("--id", required=True)
    p.add_argument("--pass", dest="passed", action="store_true")
    p.add_argument("--fail", dest="passed", action="store_false")
    p.set_defaults(passed=None)
    p.set_defaults(func=cmd_retest)

    p = sub.add_parser("stats", help="错误画像")
    p.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    C.ensure()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
