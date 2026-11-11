"""把 outline.json 生成可交互 HTML 知识地图（零外部依赖，单文件）。

用法：
    python scripts/build_atlas.py <slug> [--open]

可选输入（放在同目录）：
    mastery.json   {"章节标题": "ok"|"warn"|"blank"}   掌握度标记
    quiz.json      检索题。两种形态：
                   选择题  {"node":..,"q":..,"a":..,"correct":"B",
                            "options":[{"k":"A","text":..,"cause":"M"},…]}
                   短答题  {"node":..,"q":..,"a":..}        （没有 options）
                   有 options 时页面上可点选，点完立刻标对错并告知干扰项错因。
                   出完题跑 scripts/check_quiz.py 过一遍规则再生成。

为什么不用 markmap / mermaid CDN：
    离线能开、断网能开、发给别人也能开。原生 <details> 就够折叠了。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CSS = """
:root{
  --bg:#fbfaf8; --panel:#ffffff; --ink:#1e1c1a; --muted:#6b6560;
  --line:#e6e1da; --accent:#b4532a; --ok:#2f7d4f; --warn:#b8860b; --bad:#a83232;
}
@media (prefers-color-scheme:dark){
  :root{ --bg:#16130f; --panel:#1f1b17; --ink:#ece6dd; --muted:#a09a92;
         --line:#332d26; --accent:#e08a5c; --ok:#6cc08d; --warn:#d8ab4a; --bad:#e07070; }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;}
header{padding:28px 32px 20px;border-bottom:1px solid var(--line);background:var(--panel)}
h1{margin:0 0 6px;font-size:22px;letter-spacing:-.3px}
.sub{color:var(--muted);font-size:13px}
.stats{display:flex;gap:18px;margin-top:14px;flex-wrap:wrap}
.stat{font-size:12px;color:var(--muted)}
.stat b{display:block;font-size:19px;color:var(--ink);font-weight:600}
main{display:grid;grid-template-columns:minmax(260px,34%) 1fr;gap:0;min-height:calc(100vh - 170px)}
#tree{padding:18px 14px 40px;border-right:1px solid var(--line);overflow:auto;max-height:calc(100vh - 170px)}
#detail{padding:26px 32px 60px;overflow:auto;max-height:calc(100vh - 170px)}
details{margin:1px 0}
summary{cursor:pointer;padding:5px 8px;border-radius:6px;list-style:none;
  display:flex;align-items:center;gap:7px;font-size:14px}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸";color:var(--muted);font-size:11px;transition:transform .15s;flex:none}
details[open]>summary::before{transform:rotate(90deg)}
summary:hover{background:rgba(180,83,42,.07)}
.leaf{cursor:pointer;padding:5px 8px 5px 26px;border-radius:6px;font-size:14px;
  display:flex;gap:7px;align-items:baseline}
.leaf:hover{background:rgba(180,83,42,.07)}
.leaf.active{background:rgba(180,83,42,.13);font-weight:600}
.dot{flex:none;width:7px;height:7px;border-radius:50%;background:var(--line);margin-top:6px}
.dot.ok{background:var(--ok)} .dot.warn{background:var(--warn)} .dot.blank{background:var(--bad)}
.children{padding-left:12px;border-left:1px dashed var(--line);margin-left:9px}
h2{font-size:19px;margin:0 0 4px}
.crumb{color:var(--muted);font-size:12px;margin-bottom:20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:16px 18px;margin:14px 0}
.card h3{margin:0 0 10px;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.q{font-weight:600;margin:0 0 8px}
details.ans summary{font-size:13px;color:var(--accent);padding:0}
details.ans{padding:0}
.empty{color:var(--muted);font-size:14px;padding:30px 0}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:20px;
  border:1px solid var(--line);color:var(--muted);margin-left:6px;vertical-align:middle}
.qblock{padding:14px 0;border-top:1px dashed var(--line)}
.qblock:first-of-type{border-top:none;padding-top:0}
.opts{display:flex;flex-direction:column;gap:6px;margin:8px 0}
.opt{display:flex;gap:9px;align-items:baseline;padding:7px 11px;border:1px solid var(--line);
  border-radius:8px;cursor:pointer;font-size:14px;line-height:1.55;background:var(--bg)}
.opt:hover{border-color:var(--accent)}
.opt b{color:var(--muted);font-weight:600;flex:none}
.opt.ok{border-color:var(--ok);background:rgba(47,125,79,.10)}
.opt.ok b{color:var(--ok)}
.opt.bad{border-color:var(--bad);background:rgba(168,50,50,.09)}
.opt.bad b{color:var(--bad)}
.qblock[data-done="1"] .opt{cursor:default}
.fb{font-size:13px;min-height:0}
.fbok{color:var(--ok)} .fbbad{color:var(--bad)}
footer{padding:16px 32px;border-top:1px solid var(--line);color:var(--muted);
  font-size:12px;background:var(--panel)}
@media(max-width:820px){main{grid-template-columns:1fr}
  #tree{max-height:40vh;border-right:none;border-bottom:1px solid var(--line)}}
"""


def build_tree(items: list[dict]) -> list[dict]:
    root: dict = {"title": "", "level": 0, "children": []}
    stack = [root]
    for it in items:
        node = {
            "title": it.get("title", ""),
            "level": int(it.get("level", 1)),
            "words": it.get("words", 0),
            "children": [],
        }
        while len(stack) > 1 and stack[-1]["level"] >= node["level"]:
            stack.pop()
        stack[-1]["children"].append(node)
        stack.append(node)

    # 父节点字数 = 自身 + 全部子孙（否则章级永远是 0，因为内容都挂在节上）
    def agg(n: dict) -> int:
        n["words"] = n.get("words", 0) + sum(agg(c) for c in n["children"])
        return n["words"]

    for r in root["children"]:
        agg(r)
    return root["children"]


def render_tree(nodes: list[dict], mastery: dict, level: int = 0) -> str:
    out = []
    for n in nodes:
        t = html_escape(n["title"])
        state = mastery.get(n["title"], "")
        dot = f'<span class="dot {state}"></span>' if state else '<span class="dot"></span>'
        if n["children"]:
            openattr = " open" if level < 1 else ""
            out.append(
                f"<details{openattr}><summary>{dot}{t}</summary>"
                f'<div class="children">{render_tree(n["children"], mastery, level + 1)}</div></details>'
            )
        else:
            out.append(f'<div class="leaf" data-title="{t}">{dot}<span>{t}</span></div>')
    return "".join(out)


def html_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


JS = r"""
const DATA = __DATA__;
const nodes = DATA.nodes, mastery = DATA.mastery, quiz = DATA.quiz;
const detail = document.getElementById('detail');
const CAUSE = {K:'知识缺口',M:'概念误解',P:'程序错误',R:'表征错误',T:'迁移失败'};

function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function qBlock(x, i){
  const correct = x.correct || '';
  const hasOpts = !!(x.options && x.options.length);
  let h = `<div class="qblock" data-correct="${esc(correct)}">`;
  h += `<p class="q">${i+1}. ${esc(x.q)}</p>`;
  if(hasOpts){
    h += '<div class="opts">';
    x.options.forEach(o => {
      h += `<div class="opt" data-ok="${o.k === correct ? '1' : '0'}" data-k="${esc(o.k)}" data-c="${esc(o.cause || '')}">`
         + `<b>${esc(o.k)}</b><span>${esc(o.text)}</span></div>`;
    });
    h += '</div><div class="fb"></div>';
  }
  h += `<details class="ans"><summary>${hasOpts ? '对完答案再看' : '先自己说一遍，再展开'}</summary>`
     + `<p>${esc(x.a)}</p></details>`;
  return h + '</div>';
}

function show(title){
  const node = nodes.find(n => n.title === title);
  const state = mastery[title] || '';
  const stateTxt = {ok:'已掌握',warn:'有偏差',blank:'空白'}[state] || '未评估';
  const qs = quiz.filter(x => x.node === title || (node && node.path.includes(x.node)));
  const crumb = node ? node.path.slice(0,-1).join(' / ') || '顶层' : '';
  let h = `<h2>${esc(title)}<span class="tag">${stateTxt}</span></h2>`;
  h += `<div class="crumb">${esc(crumb)}</div>`;
  if(qs.length){
    h += `<div class="card"><h3>先答，再看答案</h3>` + qs.map(qBlock).join('') + `</div>`;
  } else {
    h += `<div class="card"><h3>这一节还没有题</h3>
      <p>比看笔记有用的一件事：现在闭卷说出这一节的<b>三个要点</b>，
      然后让我对照书里内容标出你漏了什么。</p></div>`;
  }
  if(state === 'blank'){
    h += `<div class="card"><h3>标记为空白</h3>
      <p>先别读正文。用最小示范建立框架 → 复述 → 再读。</p></div>`;
  }
  detail.innerHTML = h;
  document.querySelectorAll('.leaf').forEach(el => el.classList.toggle('active', el.dataset.title === title));
}

detail.addEventListener('click', ev => {
  const el = ev.target.closest('.opt');
  if(!el) return;
  const blk = el.closest('.qblock');
  if(!blk || blk.dataset.done === '1') return;
  blk.dataset.done = '1';
  const isRight = el.dataset.ok === '1';
  el.classList.add(isRight ? 'ok' : 'bad');
  if(!isRight){
    blk.querySelectorAll('.opt').forEach(o => { if(o.dataset.ok === '1') o.classList.add('ok'); });
  }
  const fb = blk.querySelector('.fb');
  if(!fb) return;
  fb.innerHTML = isRight
    ? `<span class="fbok">对。正确项就是 ${esc(blk.dataset.correct)}。</span>`
    : `<span class="fbbad">错。你选的这项是「${esc(CAUSE[el.dataset.c] || '干扰项')}」型（${esc(el.dataset.c || '?')}）。`
      + `先别急着看答案——这类错误以后会在哪里骗到你？</span>`;
});

document.querySelectorAll('.leaf').forEach(el => {
  el.addEventListener('click', () => show(el.dataset.title));
});
"""


def build_html(meta: dict, tree: list[dict], mastery: dict, quiz: list[dict]) -> str:
    flat = []

    def walk(ns, path):
        for n in ns:
            p = path + [n["title"]]
            flat.append({"title": n["title"], "path": p, "words": n.get("words", 0)})
            walk(n["children"], p)

    walk(tree, [])

    counts = {"ok": 0, "warn": 0, "blank": 0}
    for v in mastery.values():
        if v in counts:
            counts[v] += 1
    total_leaf = len(flat)
    evaluated = sum(counts.values())

    data = json.dumps(
        {"meta": meta, "nodes": flat, "mastery": mastery, "quiz": quiz},
        ensure_ascii=False,
    )
    # 章节标题来自第三方 EPUB，不可控。若标题含 </script>，会提前闭合脚本块、
    # 让整页报废，同时也是一条注入路径。<\/ 在 JSON 里是合法转义，解析后还原。
    data = data.replace("</", "<\\/")
    js = JS.replace("__DATA__", data)

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html_escape(meta.get('title','知识地图'))} · 结构地图</title>
<style>{CSS}</style></head>
<body>
<header>
  <h1>{html_escape(meta.get('title','未命名'))}</h1>
  <div class="sub">{html_escape(meta.get('author') or '作者未记录')} · 生成于 {date.today().isoformat()}</div>
  <div class="stats">
    <div class="stat"><b>{meta.get('chapters', total_leaf)}</b>目录节点</div>
    <div class="stat"><b>{meta.get('words', 0):,}</b>字数</div>
    <div class="stat"><b>{evaluated}/{total_leaf}</b>已评估</div>
    <div class="stat"><b>{counts['ok']}</b>已掌握</div>
    <div class="stat"><b>{counts['warn']}</b>有偏差</div>
    <div class="stat"><b>{counts['blank']}</b>空白</div>
  </div>
</header>
<main>
  <div id="tree">{render_tree(tree, mastery)}</div>
  <div id="detail">
    <h2>先别看这张图</h2>
    <div class="crumb">这是整个技能里最反直觉的一条规则</div>
    <div class="card">
      <h3>为什么</h3>
      <p>检索练习组的延迟测验成绩显著高于概念图组，而概念图组<b>事后自我感觉更好</b>
      （Karpicke &amp; Blunt, <i>Science</i>, 2011）。看图的收益接近零，被图考才有收益。</p>
      <p>所以正确用法是：<b>点左边任意节点 → 我会问你关于它的问题 → 你闭卷答 → 再看答案。</b></p>
    </div>
    <div class="card">
      <h3>怎么标记掌握度</h3>
      <p>在 <code>mastery.json</code> 里给章节标题打标记：<code>"ok"</code> 已掌握、
      <code>"warn"</code> 有偏差、<code>"blank"</code> 空白。左边的小圆点会变色。</p>
    </div>
    <div class="card">
      <h3>三个层级怎么用</h3>
      <p><b>目录树</b>（当前页）用来定位 · <b>概念依赖图</b>用来理解顺序 ·
      <b>概念对照表</b>用来防混淆。不要一次看三个，会过载。</p>
    </div>
  </div>
</main>
<footer>study-os · 图是题目来源，不是阅读材料。</footer>
<script>{js}</script>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="生成知识地图 HTML")
    ap.add_argument("slug")
    ap.add_argument("--open", action="store_true", help="生成后自动打开（Windows）")
    args = ap.parse_args()

    base = C.HOME / "atlas" / args.slug
    if not base.exists():
        print(f"[err] 找不到 {base}，先跑 extract_book.py", file=sys.stderr)
        return 1

    meta_f = base / "meta.json"
    outline_f = base / "outline.json"
    if not outline_f.exists():
        print(f"[err] 缺 outline.json", file=sys.stderr)
        return 1

    meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {"title": args.slug}
    outline = json.loads(outline_f.read_text(encoding="utf-8"))
    mastery_f = base / "mastery.json"
    quiz_f = base / "quiz.json"
    mastery = json.loads(mastery_f.read_text(encoding="utf-8")) if mastery_f.exists() else {}
    quiz = json.loads(quiz_f.read_text(encoding="utf-8")) if quiz_f.exists() else []

    tree = build_tree(outline)
    html = build_html(meta, tree, mastery, quiz)
    out = base / "atlas.html"
    out.write_text(html, encoding="utf-8")

    print(f"[ok] {out}")
    print(f"     {len(outline)} 个节点，{len(quiz)} 道题，{len(mastery)} 条掌握度标记")
    if not quiz:
        print("     提示：还没有 quiz.json，导图暂时只能当目录用——收益接近零。")
        print("     先让我出题并写成 quiz.json，再重新生成。")

    if args.open:
        import webbrowser

        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
