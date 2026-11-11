"""模式 B 交付前校验 —— 把「人工核对」变成能算的数字。

用法：
    python scripts/verify_atlas.py <slug>
    python scripts/verify_atlas.py <slug> --digest 自定义.md --outline 自定义.json
    python scripts/verify_atlas.py path/to/atlas_dir

为什么存在这个脚本：原来的校验表五格里写着「人工核对」，而人工核对在
实际使用中会退化成「我读了一遍，觉得挺好」。校验表一旦可以自我签发，
它就不再是校验，只是仪式。

能算的（C1/C2/C3）在这里算；算不出的（C4 数值代入、C5 白纸复述）
只输出待办清单，并在结论里明确标成「未自动验证」——不许拿脚本的
PASS 冒充五项全过。

退出码：0 = C1/C2/C3 全过；1 = 有硬项不过（此时不许交付）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

# 判据阈值（与 references/book-atlas.md §3.3 必须一致）
MIN_COVERAGE = 1.0        # C1：大纲节点一个都不许漏
MIN_TRACE = 0.80          # C2：可溯源比例下限
MAX_INFER = 0.20          # C2：推断标注比例上限
CORE_MARKERS = ("定义", "公式", "例", "适用")  # C3 四要素

SKIP_HINTS = ("选读", "（略）", "(略)", "[skip]")

HEAD_RE = re.compile(r"^(#{1,4})\s+(.*)$")
FENCE_RE = re.compile(r"^```")
NUM_RE = re.compile(r"^\s*(\d+(\.\d+)*)[\s.、]*")
CHAP_RE = re.compile(r"^第\s*[一二三四五六七八九十百零〇\d]+\s*[章节篇部]\s*")


def strip_number(title: str) -> str:
    """「第一章 向量空间」→「向量空间」；「1.2 基与维数」→「基与维数」。"""
    s = CHAP_RE.sub("", title.strip())
    s = NUM_RE.sub("", s)
    s = s.strip(" -—·.、:：")
    return s or title.strip()


def resolve(arg: str) -> tuple[Path, Path, Path]:
    """返回 (digest.md, outline.json, atlas.html)。参数可以是 slug、目录或 digest 文件。"""
    p = Path(arg)
    if p.is_file() and p.suffix == ".md":
        base = p.parent
        return p, base / "outline.json", base / "atlas.html"
    if p.is_dir():
        base = p
    else:
        base = C.HOME / "atlas" / arg
    return base / "digest.md", base / "outline.json", base / "atlas.html"


def load_outline(path: Path) -> list:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"[warn] outline.json 解析失败：{exc.__class__.__name__}")
        return []
    out = []
    for it in raw if isinstance(raw, list) else []:
        if isinstance(it, dict) and it.get("title"):
            out.append({"title": str(it["title"]).strip(),
                        "level": int(it.get("level") or 1)})
    return out


def split_sections(text: str, min_level: int = 3) -> list[dict]:
    """按 ##/###/#### 切节。代码块内的 # 不算标题（否则把注释当节）。

    C3/C4 只看 ### 及以下（章级标题不是概念，没有"四要素"一说）；
    C2 的节级检查放宽到 ##，否则「## 概念对照表」这类节会整个逃过检查。
    """
    sections, cur = [], None
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line.strip()):
            in_fence = not in_fence
        m = None if in_fence else HEAD_RE.match(line)
        if m and len(m.group(1)) >= min_level:
            cur = {"title": m.group(2).strip(), "lines": []}
            sections.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
    return sections


def check_c1(outline: list, text: str) -> tuple[bool, list[str], str]:
    if not outline:
        return False, ["(outline.json 缺失或为空，无法核算覆盖率)"], "无法计算"
    missing = []
    for node in outline:
        core = strip_number(node["title"])
        # 短词（≤1 字）用完整标题匹配，避免"值""图"这种误命中
        needle = core if len(core) >= 2 else node["title"]
        if needle not in text and node["title"] not in text:
            missing.append(f"L{node['level']} {node['title']}")
    hit = len(outline) - len(missing)
    rate = hit / len(outline)
    return not missing, missing, f"{hit}/{len(outline)} 命中（{rate:.0%}）"


SELF_MARK = ("验算", "推导", "代入", "自查")
SKIP_SECTION = ("闭卷", "自测", "答案", "复述题")


def check_c2(text: str) -> tuple[bool, dict]:
    """分母 = 断言型实质行，即「在陈述书中知识」的行。

    口径是这里最容易作弊的地方，所以排除项写死并单独计数：
      - 标题行、空行、引用块（>）、表格行、表格分隔线、长度 <12 的行
      - 「验算/推导/代入/自查」开头的行：那是我自己算的，本来就不该有原书页码。
        它们由 C4 负责（数值必须真代），不该混进溯源率充数或拉低分数
      - 「闭卷/自测/答案/复述题」整节：题目和答案不是知识断言

    剩下的每一行都必须带 [§x.y] 或（推断，非原文）。改口径就能刷分，
    所以排除项必须是「本来就不该溯源的东西」，不能是「不方便溯源的东西」。
    """
    lines, fences, in_fence = [], [], False
    skip_depth = 0          # >0 表示正处于被跳过的节内
    self_computed = 0
    for raw in text.splitlines():
        s = raw.strip()
        if FENCE_RE.match(s):
            in_fence = not in_fence
            continue
        if in_fence:
            fences.append(s)
            continue
        m = HEAD_RE.match(s)
        if m:
            if len(m.group(1)) <= 2:
                skip_depth = 0
            if any(h in m.group(2) for h in SKIP_SECTION):
                skip_depth = len(m.group(1))
            elif skip_depth and len(m.group(1)) > skip_depth:
                pass          # 子节，仍在跳过范围内
            else:
                skip_depth = 0
            continue
        if skip_depth:
            continue
        if not s or s.startswith(">") or s.startswith("|") or s.startswith("<!--"):
            continue
        if re.fullmatch(r"[-:|\s]+", s) or len(s) < 12:
            continue
        if s.startswith(SELF_MARK):
            self_computed += 1
            continue
        lines.append(s)
    # 代码块里的公式不计入断言行：公式本体不携带语义，出处标在引入它的那句上
    # （`**公式**：… [§1.1]`）。否则每块公式都会被判成无溯源，逼人往公式里塞标记。

    traced = inferred = 0
    untraced = []
    for s in lines:
        if "[§" in s:
            traced += 1
        elif "推断" in s and ("非原文" in s or "未经核实" in s):
            traced += 1
            inferred += 1
        else:
            untraced.append(s)
    total = len(lines)
    ok = (total > 0
          and traced / total >= MIN_TRACE
          and inferred / total <= MAX_INFER)
    return ok, {
        "total": total, "traced": traced, "inferred": inferred,
        "untraced": untraced, "self_computed": self_computed,
        "fences": len([x for x in fences if len(x) >= 12]),
        "rate": traced / total if total else 0.0,
    }


def check_c2_sections(sections: list) -> list[str]:
    """节级兜底：每个非跳过节至少要有一处 [§]。

    行级比例可以被稀释（把长句拆成短句就能把无标记行压到 20% 以下），
    节级检查挡的就是这个：整整一节没有任何出处，比例再好看也不算过。
    """
    lacking = []
    for sec in sections:
        if any(h in sec["title"] for h in SKIP_SECTION):
            continue
        body = "\n".join(sec["lines"]).strip()
        if not body:
            continue           # 章级容器节，正文都在子节里，不单独要求出处
        if "[§" not in body:
            lacking.append(sec["title"])
    return lacking


def check_c3(sections: list) -> tuple[bool, list[str]]:
    problems = []
    for sec in sections:
        if any(h in sec["title"] for h in SKIP_HINTS):
            continue
        body = "\n".join(sec["lines"])
        lacking = [k for k in CORE_MARKERS if k not in body]
        if lacking:
            problems.append(f"{sec['title']} 缺：{'/'.join(lacking)}")
    return not problems, problems


def scan_c4(sections: list) -> list[str]:
    """只找「该验算但没验算」的节，不假装能替你算。"""
    todo = []
    for sec in sections:
        if any(h in sec["title"] for h in SKIP_HINTS):
            continue
        body = "\n".join(sec["lines"])
        if re.search(r"\d", body) and "例" in body:
            if not any(k in body for k in ("验算", "代入", "带进去", "算一遍")):
                todo.append(sec["title"])
    return todo


C5_QUESTIONS = (
    "① 全书的核心问题是什么（一句话，不许用书名里的词）",
    "② 方法论主线（作者用什么思路解决它）",
    "③ 哪两章最容易被读成同一件事，区别在哪",
    "④ 只留三章，你删哪三章、为什么",
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="模式 B 交付前校验（C1/C2/C3 可算，C4/C5 人工）")
    ap.add_argument("target", help="slug、atlas 目录，或 digest.md 路径")
    ap.add_argument("--digest", help="覆盖 digest.md 路径")
    ap.add_argument("--outline", help="覆盖 outline.json 路径")
    ap.add_argument("--quiet", action="store_true", help="只输出结论")
    args = ap.parse_args(argv)

    digest, outline_path, html = resolve(args.target)
    digest = Path(args.digest) if args.digest else digest
    outline_path = Path(args.outline) if args.outline else outline_path

    if not digest.exists():
        print(f"[FAIL] 找不到 {digest}")
        print("       模式 B 的三件套第一件就是 digest.md，没有它没法校验。")
        return 1
    try:
        text = digest.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"[FAIL] {digest} 不是 UTF-8，先转码再校验")
        return 1

    outline = load_outline(outline_path)
    sections = split_sections(text)

    c1_ok, c1_missing, c1_msg = check_c1(outline, text)
    c2_ok, c2 = check_c2(text)
    c2_missing_sections = check_c2_sections(split_sections(text, min_level=2))
    c3_ok, c3_problems = check_c3(sections)
    c4_todo = scan_c4(sections)

    if not args.quiet:
        print("=" * 58)
        print(f"模式 B 交付前校验　{digest.name}")
        print("=" * 58)

        print(f"\n== C1 覆盖率 ==　{'PASS' if c1_ok else 'FAIL'}")
        print(f"   大纲节点/{len(outline)}　{c1_msg}")
        for m in c1_missing[:20]:
            print(f"   ✗ {m}")

        print(f"\n== C2 溯源率 ==　{'PASS' if c2_ok else 'FAIL'}"
              f"（门槛 ≥{MIN_TRACE:.0%}，推断 ≤{MAX_INFER:.0%}）")
        print(f"   断言行 {c2['total']}　可溯源 {c2['traced']}（{c2['rate']:.1%}）"
              f"　其中推断标注 {c2['inferred']}　｜　自算行 {c2['self_computed']}（不计入）")
        for s in c2["untraced"][:5]:
            print(f"   ✗ 无标记：{s[:56]}{'…' if len(s) > 56 else ''}")
        if len(c2["untraced"]) > 5:
            print(f"   …另有 {len(c2['untraced']) - 5} 行无标记")
        for t in c2_missing_sections:
            print(f"   ✗ 整节无出处：{t}")

        print(f"\n== C3 三件套 ==　{'PASS' if c3_ok else 'FAIL'}（节数 {len(sections)}）")
        for p in c3_problems[:10]:
            print(f"   ✗ {p}")
        if len(c3_problems) > 10:
            print(f"   …另有 {len(c3_problems) - 10} 节不全")

        print(f"\n== C4 一致性（半自动）==　待人工代入 {len(c4_todo)} 节")
        for t in c4_todo[:5]:
            print(f"   □ {t}")
        print("   脚本不替你算数：公式必须真代进去，不许眼过。")

        print("\n== C5 白纸复述（人工，脚本无法代劳）==")
        for q in C5_QUESTIONS:
            print(f"   □ {q}")

        print("\n== 其他 ==")
        print(f"   {'✓' if html.exists() else '✗'} atlas.html"
              f"{'' if html.exists() else '　→ python scripts/build_atlas.py <slug>'}")

    hard_ok = c1_ok and c2_ok and c3_ok and not c2_missing_sections
    if not args.quiet:
        print("\n" + "-" * 58)
    print(f"结论：{'PASS（C1–C3 通过，C4/C5 仍需人工）' if hard_ok else 'FAIL（不许交付）'}")
    return 0 if hard_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
