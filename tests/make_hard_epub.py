"""生成一本「故意刁难」的 EPUB，用来暴露 extract_book.py 在真实书上的失效模式。

只测规范样本等于自欺：手写的 sample.epub 每个标题都是干净的 h1/h2，
每段都是 <p>，文件名全是 ASCII。真实出版物不长这样。

这本样本刻意塞进六件事，每一件都对应一个真实世界里出现过的结构：

  1. EPUB2 + NCX 目录，没有 nav.xhtml（2010 年前后的书几乎都这样）
  2. 章节文件名含中文、空格、&（XML 里要写成 &amp;，zip 里是原文）
  3. OPF 的 href 用 percent-encoding（%E7%AC%AC%201%20%E7%AB%A0…）
  4. 正文段落包在 <div class="para"> 里，不用 <p>（转换工具常这么干）
  5. 有四层标题（h1→h4），不是只有 h1/h2
  6. spine 里混着 cover.xhtml / toc.xhtml 这类非正文页

另有 drm=True 的变体：带 META-INF/encryption.xml。真实书里加密 EPUB 很常见，
解析器应该明确说"解不了"，而不是抽出一堆乱码冒充目录。

用法：
    python tests/make_hard_epub.py [输出路径] [--drm]
"""
from __future__ import annotations

import sys
import urllib.parse as up
import zipfile
from pathlib import Path

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

ENCRYPTION = """<?xml version="1.0" encoding="UTF-8"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
            xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedData>
    <enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes256-cbc"/>
    <enc:CipherData><enc:CipherReference URI="OEBPS/text/ch1.xhtml"/></enc:CipherData>
  </enc:EncryptedData>
</encryption>"""

# zip 里的真实文件名（不编码）
F_NAME = "第 1 章 绪论 & 附录.xhtml"
F2_NAME = "ch2.xhtml"

# OPF 里写成编码形式——真实书里这两种写法都有
F_HREF = up.quote(F_NAME, safe="")


def xhtml(title: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        f"<title>{title}</title><style>p{{margin:0}}</style></head><body>\n"
        f"{body}\n</body></html>"
    )


COVER = xhtml("封面", '<div class="cover"><img src="cover.jpg" alt="封面"/></div>')

TOC_PAGE = xhtml("目录", '<div class="para">目录页，很多书在这里放一行行链接。</div>')

CH1 = xhtml(
    "第一部",
    # 章标题用 h2：EPUB2 里 h1 常留给"部"，章是 h2
    "<h1>第一部 基础</h1>\n"
    "<h2>第 1 章 绪论</h2>\n"
    # 段落用 div 而不是 p
    '<div class="para">这本书要解决的问题是：如何在没有坐标系的情况下谈论方向与长度。'
    "答案是把向量从箭头里解放出来，只保留加法与数乘两种运算。</div>\n"
    "<h3>1.1 定义</h3>\n"
    '<div class="para">向量空间是定义了加法与数乘、且对二者封闭的集合。</div>\n'
    "<h4>1.1.1 细则</h4>\n"
    '<div class="para">封闭性要求两种运算的结果仍在同一集合内，不许跑到集合外面去。</div>\n'
    # 故意留一个没闭合的 <p>，真实书里这种脏 HTML 很常见
    "<p>这里故意不闭合段落，看解析器会不会把后面整段吞掉。",
)

CH2 = xhtml(
    "第 2 章",
    "<h2>第 2 章 方法</h2>\n"
    '<div class="para">方法是先找一组基，再把所有运算翻译成坐标运算。</div>\n'
    "<h3>2.1 矩阵表示</h3>\n"
    '<div class="para">把基向量的像按列拼起来，就得到该变换在这组基下的矩阵。</div>',
)

NCX = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="hard-sample"/></head>
  <docTitle><text>刁难样本</text></docTitle>
  <navMap>
    <navPoint id="n1" playOrder="1"><navLabel><text>第一部 基础</text></navLabel>
      <content src="text/%s"/>
      <navPoint id="n2" playOrder="2"><navLabel><text>第 1 章 绪论</text></navLabel>
        <content src="text/%s"/></navPoint>
    </navPoint>
    <navPoint id="n3" playOrder="3"><navLabel><text>第 2 章 方法</text></navLabel>
      <content src="text/ch2.xhtml"/></navPoint>
  </navMap>
</ncx>""" % (F_HREF, F_HREF)


def opf() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>刁难样本：真实 EPUB 的六种脏结构</dc:title>
    <dc:creator>测试</dc:creator>
    <dc:identifier id="uid">urn:uuid:hard-sample</dc:identifier>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
    <item id="tocpage" href="toc.xhtml" media-type="application/xhtml+xml"/>
    <item id="c1" href="text/{F_HREF}" media-type="application/xhtml+xml"/>
    <item id="c2" href="text/{F2_NAME}" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="cover"/>
    <itemref idref="tocpage"/>
    <itemref idref="c1"/>
    <itemref idref="c2"/>
  </spine>
</package>"""


def make(out: Path, drm: bool = False) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER, zipfile.ZIP_DEFLATED)
        if drm:
            zf.writestr("META-INF/encryption.xml", ENCRYPTION, zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/content.opf", opf(), zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/toc.ncx", NCX, zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/cover.xhtml", COVER, zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/toc.xhtml", TOC_PAGE, zipfile.ZIP_DEFLATED)
        # 注意：zip 内条目名是原文，不是 percent-encoded
        zf.writestr(f"OEBPS/text/{F_NAME}", CH1, zipfile.ZIP_DEFLATED)
        zf.writestr(f"OEBPS/text/{F2_NAME}", CH2, zipfile.ZIP_DEFLATED)
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    drm = "--drm" in sys.argv
    default = Path(__file__).parent / ("sample_hard_drm.epub" if drm else "sample_hard.epub")
    p = make(Path(args[0]) if args else default, drm=drm)
    print(f"[ok] {p}  ({p.stat().st_size} bytes){'  DRM' if drm else ''}")
