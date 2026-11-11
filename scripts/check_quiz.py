"""选择题质检 —— 把「选项设计规则」变成可判定条件。

用法：
    python scripts/check_quiz.py <slug>
    python scripts/check_quiz.py path/to/quiz.json

为什么需要它：
    references/book-atlas.md 里那套选项规则（四个选项、错误项必须标错因、
    不许出现「以上都对」、正确项不能是唯一最长的、正确项必须写边界）
    如果只写在文档里靠自觉执行，等于没执行。这个脚本把每条规则变成一个
    能算出来的条件，出完题跑一遍，过不了就不许拿去问用户。

检查项（E = 必须修，W = 建议改）：
    E1 缺 node / q
    E2 选择题选项数不是 4
    E3 选项字母非法或重复
    E4 correct 指向不存在的选项
    E5 干扰项没标错因，或错因不在 K/M/P/R/T 里
    E6 出现零信息选项（以上都对 / 都不对 / 全部正确 …）
    W1 正确项是唯一最长的那个 —— 长度线索泄漏，用户不看内容也能蒙
    W2 最长与最短相差超过 1.8 倍 —— 同上，只是弱一点
    W3 正确项没写边界（条件 / 当 / 若 / 只有 / 前提 …）—— 这题大概率只测到复述
    W4 全篇「概念误解型」干扰项占比 < 20% —— 剩下的题偏送分
    W5 有章一道题都没有
    W6 有章全是选择题、没有无选项题 —— 只测到「认得」，没测到「想得起」

退出码：有 E 返回 1；只有 W 返回 0（列出但不阻塞）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KEYS = ("A", "B", "C", "D")
CAUSE_OK = ("K", "M", "P", "R", "T")  # 浅色：C/E 不适合当干扰项错因
CAUSE_DOC = "K 知识缺口 / M 概念误解 / P 程序错误 / R 表征错误 / T 迁移失败"
BANNED = ("以上都", "都不对", "都正确", "全部正确", "都不正确", "以上均", "全都")
BOUNDARY = ("条件", "当", "若", "只有", "前提", "除非", "仅", "必须", "需要", "情况下", "时成立")


def _t(text) -> str:
    return str(text or "").strip()


def check_item(idx: int, it: dict) -> list[tuple[str, str, str]]:
    """返回 [(code, level, msg)]。"""
    out: list[tuple[str, str, str]] = []

    if not _t(it.get("node")) or not _t(it.get("q")):
        out.append(("E1", "err", "缺 node 或 q"))
        return out

    opts = it.get("options") or []
    if not opts:
        # 无选项题 = 闭卷短答，合法。只要求有答案。
        if not _t(it.get("a")):
            out.append(("E1", "err", "无选项题缺 a（短答也要给参考答案）"))
        return out

    # ---- 结构 ----
    if len(opts) != 4:
        out.append(("E2", "err", f"选项 {len(opts)} 个，必须是 4 个"))

    seen = []
    for o in opts:
        k = _t(o.get("k")).upper()
        if k not in KEYS:
            out.append(("E3", "err", f"选项字母非法：{o.get('k')!r}"))
        elif k in seen:
            out.append(("E3", "err", f"选项字母重复：{k}"))
        else:
            seen.append(k)
        if not _t(o.get("text")):
            out.append(("E3", "err", f"选项 {k or '?'} 没有正文"))

    correct = _t(it.get("correct")).upper()
    if correct not in seen:
        out.append(("E4", "err", f"correct={correct!r} 不在选项里"))

    # ---- 干扰项错因 ----
    missing = []
    for o in opts:
        k = _t(o.get("k")).upper()
        if k == correct:
            continue
        c = _t(o.get("cause")).upper()
        if not c:
            missing.append(k)
        elif c not in CAUSE_OK:
            out.append(("E5", "err", f"选项 {k} 的 cause={c!r} 不合法（只能是 {CAUSE_DOC}）"))
    if missing:
        out.append(("E5", "err", f"干扰项 {','.join(missing)} 没标错因，选错就没法定位（{CAUSE_DOC}）"))

    # ---- 零信息选项 ----
    for o in opts:
        t = _t(o.get("text"))
        for w in BANNED:
            if w in t:
                out.append(("E6", "err", f"选项 {_t(o.get('k'))} 含零信息词「{w}」：{t[:24]}"))
                break

    # ---- 长度线索 ----
    lens = {_t(o.get("k")).upper(): len(_t(o.get("text"))) for o in opts}
    lens = {k: v for k, v in lens.items() if v > 0}
    if len(lens) >= 3 and correct in lens:
        others = [v for k, v in lens.items() if k != correct]
        cl = lens[correct]
        if others:
            longest_other = max(others)
            if cl > longest_other and cl >= longest_other * 1.25:
                out.append(("W1", "warn", f"正确项最长（{cl} 字 vs 次长 {longest_other} 字），长度就是答案线索"))
            lo, hi = min(lens.values()), max(lens.values())
            if lo >= 4 and hi / lo > 1.8:
                out.append(("W2", "warn", f"选项长度 {lo}–{hi} 字，相差 {hi / lo:.1f} 倍，过长的那项会被优先读"))

    # ---- 正确项有没有写边界 ----
    for o in opts:
        if _t(o.get("k")).upper() == correct:
            t = _t(o.get("text"))
            if not any(b in t for b in BOUNDARY):
                out.append(("W3", "warn", "正确项没写成立边界（条件/当/若/只有…），这题可能只考了复述"))
    return out


def chapter_map(outline: list) -> list[tuple[str, list[str]]]:
    """把扁平 outline 切成 [(章标题, [该章下所有节点标题])]。"""
    out: list[tuple[str, list[str]]] = []
    cur = None
    for it in outline:
        try:
            lv = int(it.get("level", 1))
        except (TypeError, ValueError):
            continue
        title = _t(it.get("title"))
        if not title:
            continue
        if lv == 1:
            cur = (title, [title])
            out.append(cur)
        elif cur is not None:
            cur[1].append(title)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="选择题质检")
    ap.add_argument("target", help="slug（读 ~/.study-os/atlas/<slug>/quiz.json）或 quiz.json 路径")
    ap.add_argument("--max-warn", type=int, default=None, help="WARN 超过这个数就返回 1")
    args = ap.parse_args()

    p = Path(args.target)
    if p.suffix.lower() == ".json":
        quiz_f, base = p, p.parent
    else:
        base = C.HOME / "atlas" / args.target
        quiz_f = base / "quiz.json"

    if not quiz_f.exists():
        print(f"[err] 找不到 {quiz_f}", file=sys.stderr)
        return 1
    try:
        quiz = json.loads(quiz_f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"[err] quiz.json 不是合法 JSON：{exc}", file=sys.stderr)
        return 1
    if not isinstance(quiz, list):
        print("[err] quiz.json 顶层必须是数组", file=sys.stderr)
        return 1

    outline_f = base / "outline.json"
    outline = []
    if outline_f.exists():
        try:
            outline = json.loads(outline_f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            outline = []

    results: list[tuple[int, str, str, list]] = []
    n_choice = n_free = 0
    distractor_causes: list[str] = []

    for i, it in enumerate(quiz, 1):
        if not isinstance(it, dict):
            results.append((i, "(非对象)", "选择", [("E1", "err", "记录不是对象")]))
            continue
        opts = it.get("options") or []
        kind = "选择" if opts else "短答"
        if opts:
            n_choice += 1
            correct = _t(it.get("correct")).upper()
            for o in opts:
                if _t(o.get("k")).upper() != correct:
                    distractor_causes.append(_t(o.get("cause")).upper())
        else:
            n_free += 1
        results.append((i, _t(it.get("node")) or "(缺 node)", kind, check_item(i, it)))

    # ---- 全局：错因分布 ----
    m_ratio = 0.0
    if distractor_causes:
        m_ratio = distractor_causes.count("M") / len(distractor_causes)
        if m_ratio < 0.20:
            results.append(
                (0, "(全篇)", "—", [("W4", "warn", f"概念误解型干扰项只占 {m_ratio:.0%}，选择题会偏送分")])
            )

    # ---- 全局：章覆盖 ----
    if outline:
        chs = chapter_map(outline)
        for title, nodes in chs:
            mine = [it for it in quiz if isinstance(it, dict) and _t(it.get("node")) in nodes]
            if not mine:
                results.append((0, title, "—", [("W5", "warn", "这一章一道题都没有")]))
            elif all((it.get("options") or []) for it in mine):
                results.append(
                    (0, title, "—", [("W6", "warn", "全是选择题，缺一道无选项题（识别 ≠ 回忆）")])
                )

    # ---- 打印 ----
    errs = sum(1 for r in results for it in r[3] if it[1] == "err")
    warns = sum(1 for r in results for it in r[3] if it[1] == "warn")

    print(f"选择题质检 · {quiz_f}")
    print("-" * 72)
    print(C.pad("#", 4) + C.pad("节点", 34) + C.pad("题型", 6) + "结果")
    for i, node, kind, msgs in results:
        flags = [m for m in msgs]
        status = "ok" if not flags else f"{len(flags)} 项"
        print(C.pad(str(i) if i else "·", 4) + C.pad(node, 34) + C.pad(kind, 6) + status)
        for code, level, msg in flags:
            print(f"    [{'E' if level == 'err' else 'W'}{code[1:]} {level}] {msg}")
    print("-" * 72)
    print(f"共 {len(quiz)} 题（选择 {n_choice} / 短答 {n_free}）· ERROR {errs} · WARN {warns}")
    if errors_only(results):
        print("\n先修 ERROR 再拿去问用户。规则出处：references/book-atlas.md §2.3")
        return 1
    if warns:
        print("\nWARN 不阻塞，但 W1/W3 会直接抬高正确率，建议改掉。")
    if args.max_warn is not None and warns > args.max_warn:
        return 1
    return 0


def errors_only(results) -> bool:
    return any(it[1] == "err" for r in results for it in r[3])


if __name__ == "__main__":
    raise SystemExit(main())
