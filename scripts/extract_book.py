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

    BLOCK = {"p", "div", "br", "li", "tr"}

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
        if tag in ("h1", "h2", "h3", "h4", "p", "li"):
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


def do_epub(path: Path, slug: str) -> dict:
    out = C.HOME / "atlas" / slug
    if out.exists() and any(out.iterdir()):
        # 只覆盖 meta/outline/md；mastery.json 与 quiz.json 是用户产物，不动
        print(f"[warn] {slug} 已存在，将覆盖 meta/outline/md（mastery.json、quiz.json 保留）")
    out.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(path) as zf:
        title, author, order = epub_meta(zf)
        md_parts: list[str] = []
        outline: list[dict] = []
        total_words = 0

        for p in order:
            try:
                raw = zf.read(p).decode("utf-8", errors="ignore")
            except KeyError:
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


def do_pdf(path: Path, slug: str, toc_file: Path | None) -> dict:
    out = C.HOME / "atlas" / slug
    if out.exists() and any(out.iterdir()):
        print(f"[warn] {slug} 已存在，将覆盖 meta/outline/md（mastery.json、quiz.json 保留）")
    out.mkdir(parents=True, exist_ok=True)

    if toc_file:
        lines = [ln.strip() for ln in toc_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        outline = []
        for ln in lines:
            m = re.match(r"^(\s*)(.+)$", ln)
            indent = len(m.group(1))
            outline.append({"level": min(indent // 2 + 1, 3), "title": m.group(2), "words": 0, "file": ""})
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
        import fitz  # PyMuPDF
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
    toc = doc.get_toc()  # [[level, title, page], ...]
    outline = []
    total_words = 0
    md_parts = []
    for lvl, title, page in toc:
        outline.append({"level": min(lvl, 3), "title": title, "words": 0, "page": page, "file": ""})
    if not toc:
        outline = [{"level": 1, "title": f"第 {i+1} 页起", "words": 0, "page": i + 1} for i in range(0, len(doc), 10)]
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
    ap.add_argument("--toc", default="", help="手动目录文本（PDF 降级用，缩进表示层级）")
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
            meta = do_pdf(path, slug, toc_path)
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
