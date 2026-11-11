"""extract_book.py 在「脏 EPUB」上的行为测试。不联网。

为什么值得单独测：解析失败的方式是**静默丢章**——目录看着正常，少一章
谁也不知道。这类 bug 不会报错，只会在你复习到第三章时才发现前面断层了。

这里用 tests/make_hard_epub.py 造的书，专打六种真实结构：EPUB2+NCX、
percent-encoded href、中文文件名带空格和 &、div 包裹的段落、四层标题、
spine 混入封面页。另外测 DRM 必须明确报错而不是产出乱码。

跑法：
    python tests/test_extract.py
"""
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).parent.parent
# _common.HOME 在 import 时就求值，必须先设环境变量再 import
_TMP = tempfile.mkdtemp(prefix="study-os-test-")
os.environ["STUDY_OS_HOME"] = _TMP

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import extract_book as E  # noqa: E402
import make_hard_epub as H  # noqa: E402

PASSED = 0
FAILED = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


work = pathlib.Path(_TMP)

print("== 脏 EPUB：不许丢章 ==")
book = H.make(work / "hard.epub")
meta = E.do_epub(book, "hard")
outline = json.loads((work / "atlas/hard/outline.json").read_text(encoding="utf-8"))
titles = [n["title"] for n in outline]

check("percent-encoded href 能读到（第一章没丢）",
      any("第 1 章 绪论" in t for t in titles), str(titles))
check("四层标题全在（h1–h4）",
      all(any(t.startswith(x) for t in titles)
          for x in ("第一部", "第 1 章", "1.1 定义", "1.1.1")), str(titles))
check("封面/目录页没被当成章节", not any("封面" in t for t in titles))
check("div 包裹的段落被收进正文（字数不为 0）", meta["words"] > 100, f"words={meta['words']}")

md = (work / "atlas/hard/hard.md").read_text(encoding="utf-8")
check("div 里的正文句子在 md 里", "封闭性要求" in md)
check("未闭合 <p> 没吞掉后面的字", "不闭合段落" in md)
check("文件名里的 & 没把路径搞坏", "&" in outline[0]["file"])

print("\n== DRM：必须明确说解不开 ==")
drm = H.make(work / "drm.epub", drm=True)
try:
    E.do_epub(drm, "drm")
    check("加密书应当抛错", False, "没有抛错，等于会产出乱码目录")
except RuntimeError as exc:
    msg = str(exc)
    check("加密书抛 RuntimeError", True)
    check("消息里说清是加密问题", "加密" in msg and "DRM" in msg, msg[:60])
    check("给出替代路径", "目录" in msg)

print("\n== 正常样本仍能跑（没被改坏）==")
sys.path.insert(0, str(ROOT / "tests"))
import make_sample_epub  # noqa: E402
plain = make_sample_epub.make(work / "plain.epub")
m2 = E.do_epub(plain, "plain")
check("规范样本标题数不变", m2["chapters"] == 6, f"chapters={m2['chapters']}")
check("规范样本文本非空", m2["words"] > 50, f"words={m2['words']}")

print(f"\n{'=' * 40}\n通过 {PASSED}　失败 {FAILED}")
sys.exit(1 if FAILED else 0)
