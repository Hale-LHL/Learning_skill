"""电子书提取：EPUB（标准库）/ PDF（需 PyMuPDF，否则降级）。

用法：
    python scripts/extract_book.py <book.epub>
    python scripts/extract_book.py <book.pdf>
    python scripts/extract_book.py <book.pdf> --toc toc.txt   # 手动给目录，跳过解析

产出：
    ~/.study-os/atlas/<slug>/meta.json     书名/作者/来源/章数/字数
    ~/.study-os/atlas/<slug>/outline.json  层级目录树（扁平 level 列表）
    ~/.study-os/atlas/<slug>/<slug>.md     全文 markdown（按标题切分）

为什么 EPUB 不用 ebooklib：它是 zip + XHTML，标准库足够。
依赖越少，这个技能在别人机器上装得上的概率越高。
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import urllib.parse
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class TextExtract(HTMLParser):
    """从 XHTML 片段里抽标题与正文。"""

    # 块级容器：结束时要 flush。
    # div 必须在里面——很多转换工具把整段文字直接包在 <div class="para"> 里，
    # 不套 <p>。不认 div 的后果不是"少几段"，而是整章正文全丢，
    # 而 outline 里标题还在，看起来像"提取成功、字数 0"。
    BLOCK = {"p", "div", "br", "li", "tr", "td", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings: list[tuple[int, str]] = []
        self.blocks: list[tuple[str, str]] = []  # ("h1"|"p", text)
        self._tag: str | None = None
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip += 1
        # h1–h6 全收：四层标题的书不少见（部 / 章 / 节 / 小节）
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6",
                   "p", "li", "div", "td", "blockquote"):
            self._flush()
            self._tag = tag
            self._buf = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self._skip:
            self._skip -= 1
        if self._tag and tag == self._tag:
            self._flush()
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._skip:
            return
        if self._tag:
            self._buf.append(data)

    def _flush(self):
        if not self._tag:
            return
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if text:
            if self._tag.startswith("h"):
                lvl = int(self._tag[1])
                self.headings.append((lvl, text))
                self.blocks.append((self._tag, text))
            elif len(text) > 1:
                self.blocks.append(("p", text))
        self._tag = None
        self._buf = []


def slugify(name: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]+", "-", name).strip(" .-")
    s = re.sub(r"\s+", "-", s)
    return (s or "book")[:60]


def epub_meta(zf: zipfile.ZipFile) -> tuple[str | None, str | None, list[str]]:
    """返回 (title, author, 按 spine 排序的 xhtml 路径列表)。"""
    try:
        cont = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = cont.find(".//c:rootfile", NS)
        opf_path = rootfile.get("full-path") if rootfile is not None else None
    except (KeyError, ET.ParseError):
        opf_path = None

    if not opf_path:
        # 退化：直接找 .opf
        cands = [n for n in zf.namelist() if n.lower().endswith(".opf")]
        if not cands:
            raise RuntimeError("找不到 OPF，这个 EPUB 结构异常")
        opf_path = cands[0]

    try:
        opf = ET.fromstring(zf.read(opf_path))
    except (KeyError, ET.ParseError) as e:
        raise RuntimeError(f"OPF 读取失败（{e.__class__.__name__}）：{opf_path}") from e
    base = posixpath.dirname(opf_path)

    title = None
    author = None
    for el in opf.iter():
        tag = el.tag.split("}")[-1]
        if tag == "title" and el.text and not title:
            title = el.text.strip()
        elif tag == "creator" and el.text and not author:
            author = el.text.strip()

    manifest: dict[str, str] = {}
    for item in opf.iter():
        if item.tag.split("}")[-1] == "item":
            iid, href = item.get("id"), item.get("href")
            if iid and href:
                # href 里可能是 percent-encoding（`%E7%AC%AC%201%20%E7%AB%A0…`），
                # 而 zip 条目名是原文。不解码的话 zf.read() 抛 KeyError，
                # 而旧代码是 `except KeyError: continue`——整整一章被静默吞掉，
                # 目录里少一章也不报错。真实书上这个坑很常见。
                href = urllib.parse.unquote(href)
                manifest[iid] = posixpath.normpath(posixpath.join(base, href))

    order: list[str] = []
    for ref in opf.iter():
        if ref.tag.split("}")[-1] == "itemref":
            iid = ref.get("idref")
            if iid in manifest:
                order.append(manifest[iid])

    if not order:
        order = [v for v in manifest.values() if v.lower().endswith((".xhtml", ".html", ".htm"))]

    return title, author, order


def check_encrypted(zf: zipfile.ZipFile) -> None:
    """DRM 检测：正文被加密时必须直说，不许抽出一堆乱码冒充目录。

    encryption.xml 也用于「字体混淆」——那种只加密字体，正文能读。
    所以只在被加密的目标是 xhtml/opf 时才拦。判错方向的代价不对称：
    误报只是让用户确认一下，漏报会让他拿到一本乱码"摘要"。
    """
    try:
        raw = zf.read("META-INF/encryption.xml").decode("utf-8", "ignore")
    except KeyError:
        return
    uris = re.findall(r'URI="([^"]+)"', raw)
    hit = [u for u in uris if u.lower().endswith((".xhtml", ".html", ".htm", ".opf"))]
    if hit:
        raise RuntimeError(
            "这本 EPUB 的正文被加密了（DRM），标准库解不开。\n"
            f"      被加密的正文文件：{hit[0]}\n"
            "      换一本未加密的，或先用 Calibre 去 DRM（请自行确认合法）。\n"
            "      没有书也别停：把目录拍照或复制给我，走 PDF 的手动目录路径。"
        )


def do_epub(path: Path, slug: str) -> dict:
    out = C.HOME / "atlas" / slug
    if out.exists() and any(out.iterdir()):
        # 只覆盖 meta/outline/md；mastery.json 与 quiz.json 是用户产物，不动
        print(f"[warn] {slug} 已存在，将覆盖 meta/outline/md（mastery.json、quiz.json 保留）")
    out.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(path) as zf:
        check_encrypted(zf)
        title, author, order = epub_meta(zf)
        names = set(zf.namelist())
        md_parts: list[str] = []
        outline: list[dict] = []
        total_words = 0
        lost: list[str] = []

        for p in order:
            # 少数书是反过来：OPF 里写原文，zip 里存编码名
            real = p if p in names else urllib.parse.quote(p, safe="/")
            try:
                raw = zf.read(real).decode("utf-8", errors="ignore")
            except KeyError:
                lost.append(p)
                continue
            ex = TextExtract()
            ex.feed(raw)
            ex._flush()

            chunk: list[str] = []
            cur: dict | None = None
            for tag, text in ex.blocks:
                if tag.startswith("h"):
                    lvl = min(int(tag[1]), 3)
                    cur = {"level": lvl, "title": text, "words": 0, "file": p}
                    outline.append(cur)
                    chunk.append(f"{'#' * lvl} {text}\n")
                else:
                    total_words += len(text)
                    # 字数归到"它前面最近的那个标题"，而不是整个文件
                    if cur is not None:
                        cur["words"] += len(text)
                    chunk.append(text + "\n")
            if chunk:
                md_parts.append("\n".join(chunk))

    if not outline:
        raise RuntimeError("没提取到任何标题。这本 EPUB 可能是图片版，或标题没用 h1-h3 标记。")

    if lost:
        # 静默丢章是最阴的失败模式：目录看着正常，少了一章谁也不知道
        print(f"[warn] {len(lost)} 个 spine 文件在 zip 里找不到，已跳过（目录可能缺章）：")
        for x in lost[:3]:
            print(f"        {x}")

    meta = {
        "title": title or path.stem,
        "author": author or "",
        "source": str(path),
        "format": "epub",
        "chapters": len(outline),
        "words": total_words,
        "slug": slug,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "outline.json").write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
    body = f"# {meta['title']}\n\n" + ("作者：" + meta["author"] + "\n\n" if meta["author"] else "")
    (out / f"{slug}.md").write_text(body + "\n".join(md_parts), encoding="utf-8")
    return meta


TOC_PAGE_RE = re.compile(r"^(.*?)[.·…\s]{3,}(\d{1,4})\s*\.?\s*$")


def parse_toc_lines(lines: list[str]) -> list[dict]:
    """目录文本 → outline。行末 `…… 37` 这类页码顺手提取（要求有点分隔符，
    防止把「习题 1-3」的 3 当页码）。`#` 开头是注释。
    """
    outline = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^(\s*)(.+?)\s*$", ln)
        indent, title = len(m.group(1)), m.group(2)
        page = None
        m2 = TOC_PAGE_RE.match(title)
        if m2:
            title, page = m2.group(1).rstrip(".·… "), int(m2.group(2))
        node = {"level": min(indent // 2 + 1, 3), "title": title, "words": 0, "file": ""}
        if page is not None:
            node["page"] = page
        outline.append(node)
    return outline


def export_pages(doc, slug: str, spec: str) -> Path:
    """把指定页渲染成 PNG，供多模态阅读（扫描书的目录页转写用）。

    spec: "3-8" 或 "3,5,7-9"。1 起始，含端点。
    """
    outdir = C.HOME / "atlas" / slug / "pages"
    outdir.mkdir(parents=True, exist_ok=True)
    pages: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        elif part.strip():
            pages.append(int(part))
    exported = []
    for p in pages:
        if not 1 <= p <= doc.page_count:
            print(f"[warn] 页码 {p} 超出范围（1-{doc.page_count}），跳过")
            continue
        pix = doc[p - 1].get_pixmap(dpi=200)
        fp = outdir / f"p{p:03d}.png"
        pix.save(str(fp))
        exported.append(fp.name)
    print(f"[ok] 已导出 {len(exported)} 页到 {outdir}")
    print(f"     把目录页截图交给能看图的一侧转写成 toc.txt（一行一条，缩进表层级），")
    print(f"     再跑：python scripts/extract_book.py <书> --toc toc.txt --slug {slug}")
    return outdir


def pdf_text_chars(doc, samples: int = 5) -> int:
    """抽样估计全书文本层规模。扫描版这个数接近 0。"""
    n = doc.page_count
    idx = {max(0, min(n - 1, int(n * f))) for f in (0.1, 0.3, 0.5, 0.7, 0.9)}
    return sum(len(doc[i].get_text().strip()) for i in idx)


def do_pdf(path: Path, slug: str, toc_file: Path | None, export: str = "") -> dict:
    out = C.HOME / "atlas" / slug
    if out.exists() and any(out.iterdir()):
        print(f"[warn] {slug} 已存在，将覆盖 meta/outline/md（mastery.json、quiz.json 保留）")
    out.mkdir(parents=True, exist_ok=True)

    if toc_file:
        # 不能先 strip：缩进就是层级。注释/空行的过滤交给 parse_toc_lines
        lines = toc_file.read_text(encoding="utf-8").splitlines()
        outline = parse_toc_lines(lines)
        meta = {
            "title": path.stem,
            "author": "",
            "source": str(path),
            "format": "pdf+toc",
            "chapters": len(outline),
            "words": 0,
            "slug": slug,
        }
        (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "outline.json").write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    try:
        import pymupdf as fitz  # PyMuPDF ≥1.26 的正式名
    except ImportError:
        try:
            import fitz  # 旧版 shim
        except ImportError:
            raise SystemExit(
                "[err] PDF 提取需要 PyMuPDF：pip install pymupdf\n"
                "      不想装的话，用降级路径：\n"
                "        1) 把书的目录页截图或复制成文本，存成 toc.txt\n"
                "        2) python scripts/extract_book.py book.pdf --toc toc.txt\n"
                "      这样能拿到结构，正文按需逐章贴给我。\n"
                "      （扫描版 PDF 需要 OCR，不在本工具范围内。）"
            )

    doc = fitz.open(path)

    if export:
        export_pages(doc, slug, export)
        doc.close()
        raise SystemExit(0)

    toc = doc.get_toc()  # [[level, title, page], ...]
    text_chars = pdf_text_chars(doc)

    # 扫描版探测：无书签 + 文本层接近 0。绝不能伪造「第 X 页起」的假章节——
    # 那是"残缺目录树冒充成功"，exit 0 比报错更有害。
    if not toc and text_chars < 50:
        doc.close()
        raise SystemExit(
            f"[err] 这本 PDF 没有文本层（抽样 5 页共 {text_chars} 字符），是纯扫描版，\n"
            "      结构提取和正文提取都做不了。两条可行路径：\n"
            "\n"
            "      路径 1（要结构，推荐）：把目录页导出成图片，交给能看图的一侧转写\n"
            f"        python scripts/extract_book.py \"{path.name}\" --slug {slug} --export-pages 3-10\n"
            "        （页码按实际的目录位置改）\n"
            f"        转写成 toc.txt 后：python scripts/extract_book.py \"{path.name}\" --slug {slug} --toc toc.txt\n"
            "\n"
            "      路径 2（已有目录文本）：直接 --toc toc.txt，行末 `…… 37` 的页码会自动识别"
        )

    outline = []
    total_words = 0
    md_parts = []
    for lvl, title, page in toc:
        outline.append({"level": min(lvl, 3), "title": title, "words": 0, "page": page, "file": ""})
    if not toc:
        # 有文本层但没书签的原生 PDF：如实说没有结构，不伪造。
        print("[warn] 这本 PDF 有文本层但没有书签目录，outline 为空。", file=sys.stderr)
        print("       可用 --toc toc.txt 提供目录（缩进表层级，行末页码可自动识别）。", file=sys.stderr)
        print("       正文仍会完整导出成 md，可先用于模式 B。", file=sys.stderr)
    for i, page in enumerate(doc):
        t = page.get_text()
        total_words += len(t)
        md_parts.append(f"\n<!-- page {i+1} -->\n{t}")
    meta = {
        "title": (doc.metadata or {}).get("title") or path.stem,
        "author": (doc.metadata or {}).get("author") or "",
        "source": str(path),
        "format": "pdf",
        "chapters": len(outline),
        "words": total_words,
        "slug": slug,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "outline.json").write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / f"{slug}.md").write_text("".join(md_parts), encoding="utf-8")
    doc.close()
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description="把电子书拆成结构")
    ap.add_argument("book")
    ap.add_argument("--slug", default="")
    ap.add_argument("--toc", default="", help="手动目录文本（PDF 降级用，缩进表示层级，行末页码可自动识别）")
    ap.add_argument("--export-pages", default="", dest="export_pages",
                    help="只把指定页渲染成 PNG（如 3-10 或 3,5,7-9），供扫描书目录页转写用")
    args = ap.parse_args()

    path = Path(args.book).expanduser()
    if not path.exists():
        print(f"[err] 文件不存在：{path}", file=sys.stderr)
        return 1

    C.ensure()
    slug = args.slug or slugify(path.stem)
    try:
        if path.suffix.lower() == ".epub":
            meta = do_epub(path, slug)
        elif path.suffix.lower() == ".pdf":
            toc_path = None
            if args.toc:
                toc_path = Path(args.toc).expanduser()
                if not toc_path.exists():
                    print(f"[err] --toc 指向的文件不存在：{toc_path}", file=sys.stderr)
                    return 1
            meta = do_pdf(path, slug, toc_path, args.export_pages)
        else:
            print(f"[err] 只支持 .epub / .pdf，收到 {path.suffix}", file=sys.stderr)
            return 1
    except zipfile.BadZipFile as e:
        print(f"[err] 不是有效的 EPUB（zip 结构损坏或文件被截断）：{e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"[err] {e}", file=sys.stderr)
        return 1

    print(f"[ok] {meta['title']}  ({meta['chapters']} 个标题, 约 {meta['words']} 字)")
    print(f"     目录：{C.HOME / 'atlas' / slug}")
    print(f"\n     下一步别急着看图。先出题：一章 4 道选择题 + 1 道无选项短答。")
    print(f"     出完跑质检：python scripts/check_quiz.py {slug}   （E 类不过不许问人）")
    print(f"     生成导图：  python scripts/build_atlas.py {slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
