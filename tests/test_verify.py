"""verify_atlas.py 的口径测试。不联网、不依赖真实书。

为什么这个测试比别的重要：C2 的溯源率是最容易作弊的一格——改口径就能把
80% 刷到 100%。所以这里既测"抓得住"（缺覆盖率、整节无出处、缺要素会被拦），
也测"不误伤"（自算的验算式、闭卷题、代码块公式不该被算成无溯源）。

跑法：
    python tests/test_verify.py
"""
import io
import pathlib
import re
import sys
import tempfile
import contextlib

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import verify_atlas as V  # noqa: E402

PASSED = 0
FAILED = 0
SAMPLE = (ROOT / "tests" / "sample_digest.md").read_text(encoding="utf-8")
OUTLINE = '[' + ",".join(
    '{"level": %d, "title": "%s"}' % (lv, t) for lv, t in [
        (1, "第一章 向量空间"), (2, "1.1 线性无关"), (2, "1.2 基与维数"),
        (1, "第二章 线性变换"), (2, "2.1 线性变换的定义"), (2, "2.2 矩阵表示"),
    ]) + ']'


def check(name: str, cond: bool, detail: str = ""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def run(text: str, outline: str = OUTLINE) -> tuple[int, str]:
    """把内容和大纲写进临时目录，跑一遍，返回 (退出码, 输出)。"""
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        (d / "digest.md").write_text(text, encoding="utf-8")
        (d / "outline.json").write_text(outline, encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = V.main([str(d)])
    return code, buf.getvalue()


print("== 合格样本应当通过 ==")
code, out = run(SAMPLE)
check("总判定 PASS", code == 0, out[-160:])
check("C1 6/6", "6/6 命中" in out)

print("\n== C1：漏一个大纲节点必须拦下 ==")
code, out = run(SAMPLE.replace("### 2.2 矩阵表示", "### 矩阵的另一种说法"))
check("缺节点 → FAIL", code == 1)
check("报出缺的是哪节", "2.2 矩阵表示" in out)

print("\n== C1：只差编号也算命中（标题核心词匹配）==")
code, out = run(SAMPLE.replace("### 2.2 矩阵表示", "### 2.2　矩阵表示（改过空格）"))
check("全角空格不影响", code == 0, out[-120:])

print("\n== C2：把出处全删掉必须拦下 ==")
code, out = run(re.sub(r"\[§[\d.]+\]", "", SAMPLE))
check("无溯源 → FAIL", code == 1)
check("报告里点名溯源率", "溯源率" in out and "FAIL" in out)

print("\n== C2：整节无出处（比例仍很高）必须拦下 ==")
half = SAMPLE.replace("[§2.1]", "[§2.1）")   # 保留一半以上的合法标记
one = re.sub(r"\[§2\.2\]", "", half)          # 只清掉 2.2 节的
code, out = run(one)
check("单节无出处 → FAIL", code == 1)
check("点名整节", "整节无出处" in out)

print("\n== C2：自算行与闭卷题不该被算成无溯源 ==")
_, c2 = V.check_c2(SAMPLE)
check("验算 4 行被单独计数", c2["self_computed"] == 4, f"实际 {c2['self_computed']}")
check("闭卷三题未进入分母", "超过空间维数" not in " ".join(c2["untraced"]))
check("代码块公式未进入分母", "k₁v₁" not in " ".join(c2["untraced"]))
check("断言行数合理（15–30）", 15 <= c2["total"] <= 30, f"实际 {c2['total']}")

print("\n== C3：缺一个要素必须拦下 ==")
code, out = run(SAMPLE.replace("**公式** [§2.2]", "**扩展** [§2.2]"))
check("缺公式 → FAIL", code == 1)
check("报出缺哪一项", "缺：公式" in out)

print("\n== C3：标了（选读）的节跳过四要素检查 ==")
code, out = run(SAMPLE.replace("### 2.2 矩阵表示", "### 2.2 矩阵表示（选读）"))
check("选读节不要求四要素", code == 0, out[-140:])

print("\n== C4：有例子但没验算的节要进待办 ==")
code, out = run(SAMPLE.replace("验算：把 A 乘", "顺手写一下：把 A 乘"))
check("列出待人工代入", "待人工代入 1 节" in out, out[-200:])

print("\n== 缺 digest / 缺 outline 的降级 ==")
code, out = run(SAMPLE, outline="[]")
check("无大纲 → 不算通过", code == 1)
check("说清楚为什么", "无法核算覆盖率" in out)
with tempfile.TemporaryDirectory() as td:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = V.main([td])
    check("缺 digest → 退出码 1", code == 1)
    check("缺 digest 有提示", "模式 B 的三件套" in buf.getvalue())

print(f"\n{'=' * 40}\n通过 {PASSED}　失败 {FAILED}")
sys.exit(1 if FAILED else 0)
