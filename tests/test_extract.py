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

print("\n== toc.txt 解析（真实扫描书转写用）==")
outline = E.parse_toc_lines([
    "# 注释行要忽略",
    "绪论 …… 1",
    "第一章 函数 极限与连续 …… 4",
    "  §1.1 映射与函数 …… 4",
    "    一、集合 区间与邻域 …… 4.",
    "    习题 1-3 …… 27",
])
check("注释行被忽略", len(outline) == 5, f"n={len(outline)}")
check("章是 L1", outline[1]["level"] == 1, str(outline[1]))
check("节是 L2（缩进 2 空格）", outline[2]["level"] == 2, str(outline[2]))
check("小节是 L3（缩进 4 空格）", outline[3]["level"] == 3, str(outline[3]))
check("页码提取成功（含尾点）", outline[3].get("page") == 4, str(outline[3]))
check("「习题 1-3」不会被误当页码 3", outline[4].get("page") == 27 and "习题 1-3" in outline[4]["title"],
      str(outline[4]))
no_page = E.parse_toc_lines(["某节没有页码"])
check("没页码的行不硬造 page 字段", "page" not in no_page[0], str(no_page[0]))

# ---- 真实书测试暴露的两个坑：扫描版伪造成功、无书签伪造章节 ----
try:
    import pymupdf
    HAS_PDF = True
except ImportError:
    HAS_PDF = False
if HAS_PDF:
    print("\n== PDF：扫描版与无书签书不许伪造成功 ==")
    # 纯图 PDF（无文本层、无书签）——微积分教材的真实形态
    scan = pymupdf.open()
    page = scan.new_page()
    page.insert_image(page.rect, pixmap=pymupdf.Pixmap(pymupdf.csRGB, page.rect, False))
    scan.save(str(work / "scan.pdf"))
    scan.close()
    try:
        E.do_pdf(work / "scan.pdf", "scan", None)
        check("扫描书应当抛错", False, "没抛错 = 又要产出假目录")
    except SystemExit as exc:
        msg = str(exc)
        check("扫描书抛 SystemExit", True)
        check("说清是没有文本层", "文本层" in msg, msg[:60])
        check("给出 --export-pages 路径", "--export-pages" in msg, msg[:120])
        check("给出 --toc 路径", "--toc" in msg)

    # 有文本层但没书签：不许伪造「第 X 页起」
    native = pymupdf.open()
    p1 = native.new_page()
    p1.insert_text((72, 100), "hello calculus " * 30, fontsize=11)
    native.save(str(work / "native.pdf"))
    native.close()
    m3 = E.do_pdf(work / "native.pdf", "native", None)
    nat_outline = json.loads((work / "atlas/native/outline.json").read_text(encoding="utf-8"))
    check("无书签 PDF 的 outline 是空的（不伪造页段）", nat_outline == [], str(nat_outline)[:60])
    check("正文仍然完整导出", m3["words"] > 100, f"words={m3['words']}")

    # --toc 路径仍然可用
    toc = work / "t.txt"
    toc.write_text("第一章 试foo …… 3\n  1.1 小节 …… 5\n", encoding="utf-8")
    m4 = E.do_pdf(work / "native.pdf", "nattoc", toc)
    t_outline = json.loads((work / "atlas/nattoc/outline.json").read_text(encoding="utf-8"))
    check("--toc 手动目录生效", len(t_outline) == 2 and t_outline[1]["level"] == 2, str(t_outline))

print(f"\n{'=' * 40}\n通过 {PASSED}　失败 {FAILED}")
sys.exit(1 if FAILED else 0)
