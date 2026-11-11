"""study-os 共享状态层。仅依赖标准库。

状态根目录优先级：
  1. 环境变量 STUDY_OS_HOME
  2. ~/.study-os

健壮性约定（都是踩过坑的）：
  - 绝不调用 os.remove / Path.unlink：部分 Windows 环境的 safe-delete 中间件
    会拦成 SAFE_DELETE_FAIL_CLOSED 并抛异常，导致命令直接失败。
  - 写盘用「同目录临时文件 + os.replace」，临时名带 pid，避免并发写互相踩踏。
  - 所有日期解析走 as_date()，脏数据只影响它自己那条，不让整个 list 崩掉。
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

HOME = Path(os.environ.get("STUDY_OS_HOME") or (Path.home() / ".study-os"))

SUBDIRS = ("mistakes", "cards", "atlas", "resources", "logs")


def ensure() -> Path:
    HOME.mkdir(parents=True, exist_ok=True)
    for d in SUBDIRS:
        (HOME / d).mkdir(parents=True, exist_ok=True)
    return HOME


def _blank(default):
    return type(default)(default) if isinstance(default, (dict, list)) else default


def load(rel: str, default):
    f = HOME / rel
    if not f.exists():
        return _blank(default)
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # 备份尝试包在 try 里：rename 在 Windows 上也可能被拦或被占用。
        # 备份失败不影响主流程——原文件保持不动，比崩溃好。
        bak = f.with_name(f"{f.name}.bak-{datetime.now():%Y%m%d%H%M%S%f}")
        try:
            f.rename(bak)
            print(f"[warn] {rel} 解析失败（{exc.__class__.__name__}），已备份为 {bak.name}，使用默认值")
        except OSError:
            print(f"[warn] {rel} 解析失败且无法备份，本次使用默认值；原文件未改动")
        return _blank(default)


def save(rel: str, data) -> None:
    f = HOME / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    # 带 pid 的临时名：两个进程同时写同一份 JSON 时不会抢同一个临时文件
    tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # os.replace 在目标被其他进程短暂打开时可能抛 PermissionError，短重试
    for i in range(3):
        try:
            os.replace(tmp, f)
            return
        except PermissionError:
            if i == 2:
                raise
            time.sleep(0.05)


def today() -> date:
    return date.today()


def iso(d: date) -> str:
    return d.isoformat()


def as_date(value, fallback=None):
    """把任意输入安全转成 date。解析不了就返回 fallback，不抛异常。

    存在的理由：手改过的 JSON、被截断的文件、上游崩溃留下的半截记录，
    都会让裸 date.fromisoformat 抛 ValueError，进而让 list/stats/due 全部瘫痪。
    一条脏记录不该毁掉整个命令。
    """
    if not value:
        return fallback
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return fallback


def add_days(d: date, n: int) -> date:
    return d + timedelta(days=int(n))


def next_id(prefix: str, items: list, key: str = "id") -> str:
    """生成 <prefix>-YYYYMMDD-NNN 形式的自增 id。"""
    d = today().strftime("%Y%m%d")
    stem = f"{prefix}-{d}-"
    existing = {it.get(key) for it in items if isinstance(it, dict)}
    n = 1
    while f"{stem}{n:03d}" in existing:
        n += 1
    return f"{stem}{n:03d}"


def load_cards() -> list:
    raw = load("cards/cards.json", [])
    # 只留结构正确的记录，脏数据打一声招呼就跳过
    good = [c for c in raw if isinstance(c, dict) and c.get("id") and c.get("q")]
    for c in good:
        c.setdefault("a", "")
        c.setdefault("tag", "")
        c.setdefault("ef", 2.5)
        c.setdefault("rep", 0)
        c.setdefault("interval", 0)
        if not isinstance(c.get("history"), list):
            c["history"] = []
    if len(good) != len(raw):
        print(f"[warn] cards.json 里有 {len(raw) - len(good)} 条结构异常的记录已跳过")
    return good


def save_cards(cards: list) -> None:
    ensure()
    save("cards/cards.json", cards)


def load_mistakes() -> list:
    raw = load("mistakes/index.json", [])
    good = [m for m in raw if isinstance(m, dict) and m.get("id") and m.get("cause")]
    # 归一化：缺字段的补齐，免得下游 cmd_list / cmd_stats 到处判空
    for m in good:
        m.setdefault("topic", "(未填)")
        m.setdefault("question", "")
        m.setdefault("my_work", "")
        m.setdefault("subcause", "")
        if not isinstance(m.get("retest"), dict):
            m["retest"] = {"date": None, "passed": None}
        if not isinstance(m.get("cards"), list):
            m["cards"] = []
    if len(good) != len(raw):
        print(f"[warn] mistakes/index.json 里有 {len(raw) - len(good)} 条结构异常的记录已跳过")
    return good


def save_mistakes(items: list) -> None:
    ensure()
    save("mistakes/index.json", items)


DEFAULT_PROFILE = {
    "level": None,
    "created": None,
    "graduated": [],
    "illusions": [],
    "notes": "",
}


def load_profile() -> dict:
    p = load("profile.json", dict(DEFAULT_PROFILE))
    if not p.get("created"):
        p["created"] = iso(today())
    return p


def save_profile(p: dict) -> None:
    ensure()
    save("profile.json", p)


def log_event(kind: str, payload: dict) -> None:
    ensure()
    line = json.dumps(
        {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind, **payload},
        ensure_ascii=False,
    )
    with (HOME / "logs/sessions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def fmt_due(card: dict) -> str:
    d = as_date(card.get("due"))
    if d is None:
        return "未排期"
    delta = (d - today()).days
    if delta < 0:
        return f"逾期 {-delta} 天"
    if delta == 0:
        return "今天到期"
    return f"{delta} 天后"


def _char_w(ch: str) -> int:
    import unicodedata

    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def dwidth(s: str) -> int:
    """终端显示宽度：CJK 全角算 2。"""
    return sum(_char_w(ch) for ch in str(s))


def pad(s, w: int, align_right: bool = False) -> str:
    """按显示宽度补齐/截断，用于终端表格对齐。"""
    s = str(s)
    d = dwidth(s)
    if d <= w:
        fill = " " * (w - d)
        return fill + s if align_right else s + fill
    out, cur = "", 0
    for ch in s:
        cw = _char_w(ch)
        if cur + cw > w - 1:
            break
        out += ch
        cur += cw
    return out + "…" + " " * max(0, w - cur - 1)
