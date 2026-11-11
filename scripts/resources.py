"""资源锚点库：给知识点挂一个"换个讲法"的外部来源。

存在的理由
----------
AI 编链接是幻觉最高发的场景，而且编得特别像：BV 号格式对、标题通顺、
点开是 404。光在规则里写"不要编"没有用——模型不知道自己编了。

所以这里的约束是硬约束，不是提醒：
  * B 站视频的播放/收藏/点赞**一律走公开接口取**，不接受手填。
    取不到就入库失败，宁可不给链接，也不给一个猜的数字。
  * 每条记录都记 `checked` 日期。超过 30 天没有重新探活，
    `pick` 会把它降权并标注"未复检"。
  * 链接失效（404）直接标 dead，不再推荐。

用法
----
  python scripts/resources.py add --topic "线代/特征值" \
      --url "https://www.bilibili.com/video/BV1aW411Q7x1" \
      --note "第 42 讲，特征值定义那段从 12:30 开始"
  python scripts/resources.py add --topic "线代/特征值" \
      --url "https://zh.wikipedia.org/wiki/特征值和特征向量" --kind primary
  python scripts/resources.py probe            # 全库探活 + 刷新数字
  python scripts/resources.py pick --topic 线代
  python scripts/resources.py list
  python scripts/resources.py stats

门槛全部是**工程阈值**，没有实证依据（见 references/evidence.md §4）：
它们的作用是挡住明显的垃圾，不是判断"这个视频讲得好"。
真正的质量判断只能靠人看两分钟。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from urllib.parse import quote

from _common import (as_date, ensure, iso, load, log_event, next_id, pad,
                     save, today)

# ---------------------------------------------------------------------------
# 门槛常量。改这里就是改策略，不要散落在各处。
# ---------------------------------------------------------------------------
MIN_VIEW = 50_000        # 播放量下限：低于这个数基本是个人练习/搬运残片
MIN_FAV_LIKE = 0.6       # 收藏/点赞。知识类"留着以后用"才会收藏，
                         # 娱乐类点赞远多于收藏。这条比播放量更能区分"有用"和"好听"
MIN_FAV_RATE = 0.010     # 收藏/播放。搬运号播放高但几乎没人收藏
STALE_DAYS = 30          # 超过这么久没复检，pick 时标注并降权
AGING_YEARS = 4          # 非 evergreen 内容超过这个年限要提醒可能过时

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
BILI_RE = re.compile(r"(?:bilibili\.com/video/)?(BV[0-9A-Za-z]{10})")
BILI_API = "https://api.bilibili.com/x/web-interface/view?bvid={bvid}"


# ---------------------------------------------------------------------------
# 网络
# ---------------------------------------------------------------------------
def _get(url: str, timeout: int = 10, referer: str | None = None) -> tuple[int, bytes]:
    # 中文/空格 URL 直接丢给 urllib 会抛 UnicodeEncodeError（http.client 只收 ASCII），
    # 而且它是 ValueError 不是 URLError，原来的 except 接不住 → 整个命令崩。
    # 先把非 ASCII 百分号编码，保留已有转义不动。
    safe_url = quote(url, safe=":/?#[]@!$&'()*+,;=%")
    req = urllib.request.Request(safe_url, method="GET")
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "*/*")
    if referer:
        req.add_header("Referer", referer)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 0, b""


def fetch_bilibili(bvid: str) -> dict | None:
    """取 B 站视频真实数据。失败返回 None，绝不返回编造值。"""
    code, body = _get(BILI_API.format(bvid=bvid), referer="https://www.bilibili.com/")
    if code != 200 or not body:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if payload.get("code") != 0:
        return None
    d = payload.get("data") or {}
    stat = d.get("stat") or {}
    owner = d.get("owner") or {}
    if not d.get("title") or not stat.get("view"):
        return None
    return {
        "title": d["title"].strip(),
        "author": owner.get("name") or "",
        "author_mid": owner.get("mid"),
        "pubdate": iso(datetime.fromtimestamp(d["pubdate"]).date()) if d.get("pubdate") else None,
        "view": int(stat.get("view") or 0),
        "like": int(stat.get("like") or 0),
        "favorite": int(stat.get("favorite") or 0),
        "coin": int(stat.get("coin") or 0),
        "reply": int(stat.get("reply") or 0),
        "danmaku": int(stat.get("danmaku") or 0),
        "desc": (d.get("desc") or "")[:300],
    }


def probe_url(url: str) -> tuple[str, str]:
    """探活非 B 站链接。返回 (状态, 说明)。

    状态：ok / blocked / dead / unreachable
    区分 blocked 和 dead 很重要：403 说明页面还在，只是拒绝脚本；
    把它判成失效会导致好链接被误删。
    """
    code, body = _get(url, timeout=12)
    if code == 0:
        return "unreachable", "可能是网络问题，不是链接失效"
    if 200 <= code < 300:
        return "ok", f"HTTP {code}"
    if code in (403, 405, 418, 429, 999):
        return "blocked", f"HTTP {code}（页面多半还在，只是拒绝脚本访问）"
    if code in (404, 410):
        return "dead", f"HTTP {code}"
    return "blocked", f"HTTP {code}"


# ---------------------------------------------------------------------------
# 评分与裁决
# ---------------------------------------------------------------------------
def metrics(rec: dict) -> dict:
    view = rec.get("view") or 0
    like = rec.get("like") or 0
    fav = rec.get("favorite") or 0
    return {
        "fav_like": (fav / like) if like else 0.0,
        "fav_rate": (fav / view) if view else 0.0,
    }


def score(rec: dict) -> float:
    """**同一来源类型内**的排序分。不要跨类型比较。

    为什么不跨类型：一手来源（官方文档/论文）没有播放量，纯按流量算
    永远打不过热门视频。但"这个 API 怎么用"该先看文档，
    "这段看不懂想换个人讲"该先看视频。用法不同，排序就该由 pick 分组解决，
    不是一个万能分数能表达的。
    """
    m = metrics(rec)
    base = 0.0
    if rec.get("view"):
        base += math.log10(max(rec["view"], 10)) * 0.8
    base += min(m["fav_like"], 1.5) * 2.0
    base += min(m["fav_rate"], 0.05) * 50
    age = as_date(rec.get("pubdate"))
    if age and not rec.get("evergreen"):
        years = (today() - age).days / 365
        if years > AGING_YEARS:
            base -= 1.5
    last = as_date(rec.get("checked"))
    if last is None or (today() - last).days > STALE_DAYS:
        base -= 1.0
    return round(base, 2)


# 推荐时的固定优先级：能查到原文就先给原文，再给"换个人讲"，最后才是个人博客。
KIND_ORDER = {"primary": 0, "video": 1, "blog": 2}


def sort_key(rec: dict):
    return (KIND_ORDER.get(rec.get("kind"), 9), -score(rec))


def verdict(rec: dict) -> tuple[bool, list[str]]:
    """判断这条能不能推荐给用户。返回 (是否合格, 理由列表)。"""
    reasons: list[str] = []
    ok = True

    if rec.get("status") == "dead":
        return False, ["链接已失效"]
    if rec.get("status") in ("unreachable", "unverified", None):
        # 没探活成功就不算数。网络不通不代表链接坏，但也不代表链接好——
        # 推出去让用户撞 404 的成本，比少给一个链接高得多。
        return False, ["未验证可访问（探活没成功），先别推荐"]

    kind = rec.get("kind") or "video"
    if kind == "video":
        m = metrics(rec)
        if not rec.get("view"):
            ok = False
            reasons.append("没有播放数据（未从接口取到，不许手填）")
        elif rec["view"] < MIN_VIEW:
            ok = False
            reasons.append(f"播放 {rec['view']:,} < 门槛 {MIN_VIEW:,}")
        if m["fav_like"] < MIN_FAV_LIKE:
            ok = False
            reasons.append(f"收藏/点赞 {m['fav_like']:.2f} < {MIN_FAV_LIKE}（观众冲爽来的，不是冲用来的）")
        if m["fav_rate"] < MIN_FAV_RATE:
            ok = False
            reasons.append(f"收藏/播放 {m['fav_rate']:.2%} < {MIN_FAV_RATE:.1%}")
        if ok:
            reasons.append(f"播放 {rec['view']:,}｜收藏 {rec['favorite']:,}｜收藏率 {m['fav_rate']:.2%}")
    elif kind == "primary":
        reasons.append("一手来源（官方文档/论文/教材），不设流量门槛")
    elif kind == "blog":
        if not rec.get("author"):
            ok = False
            reasons.append("个人博客没记作者，无法判断可信度")
        if not rec.get("pubdate") and not rec.get("evergreen"):
            ok = False
            reasons.append("没记发布/更新年份，无法判断是否过时")
        if ok:
            reasons.append(f"作者 {rec.get('author')}｜{rec.get('pubdate') or '常青内容'}")

    age = as_date(rec.get("pubdate"))
    if age and not rec.get("evergreen"):
        years = (today() - age).days / 365
        if years > AGING_YEARS:
            reasons.append(f"⚠️ 已 {years:.0f} 年；若涉及工具/API/版本/考纲，先核对是否过时")

    last = as_date(rec.get("checked"))
    if last is None:
        reasons.append("⚠️ 从未探活")
    elif (today() - last).days > STALE_DAYS:
        reasons.append(f"⚠️ {(today() - last).days} 天未复检（数字会变，可能已失效）")
    if rec.get("status") == "blocked":
        reasons.append("⚠️ 脚本访问被拒，推给用户前自己点开确认一次")

    return ok, reasons


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------
REL = "resources/index.json"


def load_res() -> list:
    raw = load(REL, [])
    return [r for r in raw if isinstance(r, dict) and r.get("url")]


def save_res(items: list) -> None:
    ensure()
    save(REL, items)


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------
def cmd_add(args) -> int:
    ensure()
    url = args.url.strip()
    rec = {
        "id": None,
        "topic": args.topic.strip(),
        "url": url,
        "kind": args.kind,
        "note": args.note or "",
        "evergreen": bool(args.evergreen),
        "created": iso(today()),
        "checked": None,
        "status": "unverified",
    }

    m = BILI_RE.search(url)
    if m and args.kind == "video":
        bvid = m.group(1)
        info = fetch_bilibili(bvid)
        if info is None:
            print(f"[FAIL] 取不到 {bvid} 的数据（接口不通或视频已删）。")
            print("       按规矩不能手填播放量，这条不入库。")
            print("       换个链接，或先跑 probe 确认网络。")
            return 2
        rec.update(info)
        rec["bvid"] = bvid
        rec["url"] = f"https://www.bilibili.com/video/{bvid}"
        rec["platform"] = "bilibili"
        rec["status"] = "ok"  # 接口能返回数据 = 视频存在且可访问
        rec["author"] = info["author"]
    else:
        status, msg = probe_url(url)
        rec["status"] = status
        rec["http_note"] = msg
        rec["platform"] = "web"
        if status == "dead":
            print(f"[FAIL] {url} 返回 {msg}，链接不存在，不入库。")
            return 2
        if status == "unreachable":
            print(f"[WARN] {url} 连不上（{msg}）。已入库但标记为 unverified，先别推荐。")
        if args.title:
            rec["title"] = args.title
        if args.author:
            rec["author"] = args.author
        if args.pubdate:
            rec["pubdate"] = args.pubdate

    items = load_res()
    dup = [r for r in items if r.get("url") == rec["url"]]
    if dup:
        print(f"[SKIP] 这条已经在了：{dup[0]['id']}  {dup[0].get('title', '')}")
        return 1

    rec["id"] = next_id("R", items)
    rec["checked"] = iso(today())
    items.append(rec)
    save_res(items)
    log_event("resource_add", {"id": rec["id"], "topic": rec["topic"], "kind": rec["kind"]})

    ok, why = verdict(rec)
    print(f"[{'PASS' if ok else 'WEAK'}] {rec['id']}  {rec.get('title') or url}")
    for w in why:
        print(f"       {w}")
    if not ok:
        print("       → 不合格也能留着当参考，但 pick 不会推它。")
    if args.kind == "video" and not args.evergreen and rec.get("pubdate"):
        print("       （原理/数学这类不随版本变的内容，加 --evergreen 可去掉过时提醒）")
    return 0


def cmd_probe(args) -> int:
    items = load_res()
    if not items:
        print("库是空的。先 add 几条。")
        return 0
    targets = items
    if args.topic:
        targets = [r for r in items if args.topic in (r.get("topic") or "")]
    changed = 0
    for rec in targets:
        before = json.dumps({k: rec.get(k) for k in ("status", "view", "favorite", "like")}, sort_keys=True)
        if rec.get("bvid"):
            info = fetch_bilibili(rec["bvid"])
            if info is None:
                rec["status"] = "unreachable"
            else:
                rec.update(info)
                rec["status"] = "ok"
        else:
            status, msg = probe_url(rec["url"])
            rec["status"] = status
            rec["http_note"] = msg
        rec["checked"] = iso(today())
        after = json.dumps({k: rec.get(k) for k in ("status", "view", "favorite", "like")}, sort_keys=True)
        if before != after:
            changed += 1
    save_res(items)
    print(f"探活 {len(targets)} 条，变化 {changed} 条。")
    for rec in sorted(targets, key=sort_key):
        ok, _ = verdict(rec)
        flag = "OK " if ok else "-- "
        print(f"  {flag}{pad(rec['id'], 14)} {pad(rec.get('status', '?'), 12)} {rec.get('title') or rec['url']}")
    return 0


def cmd_pick(args) -> int:
    items = load_res()
    if not items:
        print("库是空的。")
        return 0
    pool = [r for r in items if args.topic in (r.get("topic") or "")] if args.topic else items
    if not pool:
        print(f"没有 topic 含「{args.topic}」的资源。已入库的 topic：")
        for t in sorted({r.get("topic") for r in items if r.get("topic")}):
            print("  -", t)
        return 1

    good, bad = [], []
    for rec in pool:
        ok, why = verdict(rec)
        (good if ok else bad).append((rec, why))
    good.sort(key=lambda x: sort_key(x[0]))

    print(f"== 可以推荐（{len(good)} 条）==")
    label = {"primary": "一手来源（原文/官方文档）", "video": "视频（换个讲法）", "blog": "个人博客"}
    last_kind = object()
    for rec, why in good[: args.limit]:
        kind = rec.get("kind")
        if kind != last_kind:
            print(f"-- {label.get(kind, kind)} --")
            last_kind = kind
        print(f"{rec.get('title') or rec['url']}")
        print(f"  {rec['url']}")
        if rec.get("note"):
            print(f"  备注：{rec['note']}")
        for w in why:
            print(f"  · {w}")
        print()
    if not good:
        print("  （没有合格的。宁可不给链接，也不给一条没核过的。）\n")
    if bad and args.verbose:
        print(f"== 不合格（{len(bad)} 条，只列原因）==")
        for rec, why in bad:
            print(f"  {pad(rec.get('title') or rec['url'], 40)} {'；'.join(why)}")
    return 0


def cmd_list(args) -> int:
    items = load_res()
    if not items:
        print("库是空的。")
        return 0
    if args.topic:
        items = [r for r in items if args.topic in (r.get("topic") or "")]
    for rec in sorted(items, key=lambda r: (r.get("topic") or "", sort_key(r))):
        ok, _ = verdict(rec)
        view = f"{rec['view']:,}" if rec.get("view") else "-"
        fav_like = f"{metrics(rec)['fav_like']:.2f}" if rec.get("like") else "-"
        print(
            f"{'✓' if ok else '·'} {pad(rec['id'], 14)} {pad(rec.get('topic') or '', 22)} "
            f"{pad(view, 13, True)} {pad(fav_like, 5, True)}  "
            f"{rec.get('title') or rec['url']}"
        )
    return 0


def cmd_stats(args) -> int:
    items = load_res()
    if not items:
        print("库是空的。")
        return 0
    by_topic: dict[str, list] = {}
    for rec in items:
        by_topic.setdefault(rec.get("topic") or "(未填)", []).append(rec)
    total_ok = 0
    print(f"共 {len(items)} 条，覆盖 {len(by_topic)} 个知识点\n")
    for topic, recs in sorted(by_topic.items()):
        n_ok = 0
        for r in recs:
            ok, _ = verdict(r)
            n_ok += ok
        total_ok += n_ok
        flag = "✓" if n_ok else "×"
        print(f"  {flag} {pad(topic, 26)} {n_ok}/{len(recs)} 条合格")
    print(f"\n合格 {total_ok} 条，不合格 {len(items) - total_ok} 条")
    dead = [r for r in items if r.get("status") == "dead"]
    if dead:
        print(f"\n失效 {len(dead)} 条（下次 pick 不会再出现）：")
        for r in dead:
            print(f"  {r['id']}  {r['url']}")
    stale = [r for r in items if (as_date(r.get("checked")) is None
                                 or (today() - as_date(r.get("checked"))).days > STALE_DAYS)]
    if stale:
        print(f"\n超过 {STALE_DAYS} 天未复检 {len(stale)} 条，建议跑 probe")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="study-os 资源锚点库")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="入库一条资源（B 站会自动取真实数据）")
    p.add_argument("--topic", required=True, help='用「大块/具体」格式，如 "线代/特征值"')
    p.add_argument("--url", required=True)
    p.add_argument("--kind", default="video", choices=["video", "primary", "blog"])
    p.add_argument("--note", default="", help="看哪一段、为什么推荐，越具体越有用")
    p.add_argument("--title", default="", help="非 B 站链接可手填标题")
    p.add_argument("--author", default="")
    p.add_argument("--pubdate", default="")
    p.add_argument("--evergreen", action="store_true", help="内容不随版本变化（数学原理等）")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("probe", help="全库探活 + 刷新数字")
    p.add_argument("--topic", default="")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("pick", help="按 topic 挑出可推荐的")
    p.add_argument("--topic", default="")
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=cmd_pick)

    p = sub.add_parser("list", help="列全部")
    p.add_argument("--topic", default="")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("stats", help="按知识点统计")
    p.set_defaults(func=cmd_stats)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
