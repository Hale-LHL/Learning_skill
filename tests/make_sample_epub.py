"""生成一个最小可用 EPUB，用于验证 extract_book.py 的解析链路。

用法：
    python tests/make_sample_epub.py [输出路径]
默认输出到 tests/sample.epub
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>线性代数入门</dc:title>
    <dc:creator>测试作者</dc:creator>
  </metadata>
  <manifest>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>"""

CH1 = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>第一章</title></head><body>
<h1>第一章 向量空间</h1>
<p>向量空间是一组对加法和数乘封闭的元素集合。封闭的意思是，任意两个元素相加仍在集合内，任意元素乘一个标量也仍在集合内。</p>
<h2>1.1 线性无关</h2>
<p>如果一组向量的线性组合为零向量时，所有系数都必须为零，那么这组向量线性无关。</p>
<h2>1.2 基与维数</h2>
<p>极大线性无关组叫基，基中向量的个数叫维数，它不依赖于基的选择。</p>
</body></html>"""

CH2 = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>第二章</title></head><body>
<h1>第二章 线性变换</h1>
<p>线性变换保持加法与数乘结构。它在选定基之后可以用矩阵表示。</p>
<h2>2.1 矩阵表示</h2>
<p>把基向量的像写成坐标列，拼起来就是该变换在这组基下的矩阵。</p>
<h2>2.2 特征值</h2>
<p>特征值是使 Ax = λx 有非零解的 λ，其中 x 是特征向量。</p>
</body></html>"""


def make(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    # 不调 unlink：某些 Windows 环境的 safe-delete 中间件会拦截并抛
    # SAFE_DELETE_FAIL_CLOSED。ZipFile 的 "w" 模式本身就会截断已有文件。
    with zipfile.ZipFile(out, "w") as zf:
        # mimetype 必须是第一个且不压缩，这是 EPUB 规范的硬要求
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER, zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/content.opf", OPF, zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/ch1.xhtml", CH1, zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/ch2.xhtml", CH2, zipfile.ZIP_DEFLATED)
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "sample.epub"
    p = make(target)
    print(f"[ok] {p}  ({p.stat().st_size} bytes)")
