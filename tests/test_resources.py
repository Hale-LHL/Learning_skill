"""resources.py 的裁决逻辑测试。不联网：直接构造记录喂 verdict()。

为什么单独测这个：这是整个资源机制里唯一会"放行垃圾"或"误杀好链接"的地方。
判错两个方向都有代价——放行垃圾浪费用户两分钟，误杀好链接让机制退化成不给链接。

跑法：
    python tests/test_resources.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))

import resources as R  # noqa: E402

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


def video(**kw):
    base = {
        "url": "https://www.bilibili.com/video/BV1xx",
        "kind": "video",
        "status": "ok",
        "checked": R.iso(R.today()),
        "view": 300_000,
        "like": 10_000,
        "favorite": 9_000,   # fav_like 0.90, fav_rate 3%
        "pubdate": "2025-03-01",
        "evergreen": True,
    }
    base.update(kw)
    return base


def main() -> int:
    print("== 视频：正常情况 ==")
    ok, why = R.verdict(video())
    check("高质量视频放行", ok, why)

    print("\n== 视频：流量门槛 ==")
    ok, why = R.verdict(video(view=40_000))
    check("播放 4 万被拦", not ok and any("播放" in w for w in why), why)
    ok, why = R.verdict(video(view=0))
    check("零播放被拦", not ok, why)

    print("\n== 视频：收藏/点赞比（区分'有用'和'好听'）==")
    # 娱乐向：点赞百万，收藏二十万
    ok, why = R.verdict(video(view=5_000_000, like=1_000_000, favorite=200_000))
    check("高播放低收藏被拦", not ok and any("收藏/点赞" in w for w in why), why)

    print("\n== 视频：收藏/播放比（挡搬运号）==")
    # 搬运号：播放高、点赞也还行，但几乎没人收藏
    ok, why = R.verdict(video(view=2_000_000, like=60_000, favorite=12_000))
    check("低收藏率被拦", not ok and any("收藏/播放" in w for w in why), why)

    print("\n== 状态 ==")
    ok, why = R.verdict(video(status="dead"))
    check("失效链接被拦", not ok, why)
    ok, why = R.verdict(video(status="unreachable"))
    check("未验证可访问被拦", not ok, why)
    ok, why = R.verdict(video(status="blocked"))
    check("拦截访问仍放行但提示人工确认",
          ok and any("人工" in w or "点开" in w for w in why), why)

    print("\n== 时效 ==")
    ok, why = R.verdict(video(pubdate="2015-01-01", evergreen=False))
    check("老内容放行但提醒过时",
          ok and any("过时" in w for w in why), why)
    ok, why = R.verdict(video(pubdate="2015-01-01", evergreen=True))
    check("标记 evergreen 后不再提醒过时",
          ok and not any("过时" in w for w in why), why)

    old = (R.today() - R.timedelta(days=90)).isoformat()
    ok, why = R.verdict(video(checked=old))
    check("90 天未复检放行但提醒",
          ok and any("未复检" in w for w in why), why)

    print("\n== 非视频来源 ==")
    ok, why = R.verdict({"url": "https://docs.python.org/3/x.html", "kind": "primary",
                         "status": "ok", "checked": R.iso(R.today()),
                         "title": "官方文档", "evergreen": True})
    check("一手来源不设流量门槛", ok, why)
    ok, why = R.verdict({"url": "https://blog.example.com/x", "kind": "blog",
                         "status": "ok", "checked": R.iso(R.today()),
                         "title": "某博客", "evergreen": True})
    check("博客没作者被拦", not ok and any("作者" in w for w in why), why)
    ok, why = R.verdict({"url": "https://blog.example.com/x", "kind": "blog",
                         "status": "ok", "checked": R.iso(R.today()),
                         "title": "某博客", "author": "张三",
                         "pubdate": "2025-06-01", "evergreen": True})
    check("博客作者+日期齐全放行", ok, why)

    print("\n== 排序：一手来源排在视频前面（分组，不是比分）==")
    s_primary = R.score({"kind": "primary", "status": "ok",
                         "checked": R.iso(R.today()), "evergreen": True})
    s_video = R.score(video(view=900_000, like=30_000, favorite=27_000))
    print(f"     （同类型内分数参考：官方文档 {s_primary}，热门视频 {s_video}——不可跨类型比）")
    a = {"kind": "video", "status": "ok", "checked": R.iso(R.today()),
         "evergreen": True, "view": 80_000_000, "like": 1_500_000, "favorite": 1_400_000}
    b = {"kind": "primary", "status": "ok", "checked": R.iso(R.today()),
         "evergreen": True, "title": "官方文档"}
    check("primary 的 sort_key 小于视频", R.sort_key(b) < R.sort_key(a),
          f"{R.sort_key(b)} vs {R.sort_key(a)}")
    c = {"kind": "blog", "status": "ok", "checked": R.iso(R.today()),
         "evergreen": True, "author": "x"}
    check("博客排最后", R.sort_key(a) < R.sort_key(c), f"{R.sort_key(a)} vs {R.sort_key(c)}")
    small = video(view=900_000, like=30_000, favorite=27_000)
    big = video(view=3_000_000, like=100_000, favorite=90_000)
    check("同类型内分数随播放上升", R.score(small) < R.score(big),
          f"{R.score(small)} vs {R.score(big)}")
    # sort_key 里分数取了负（升序排列 = 高分在前），所以高分那条 sort_key 更小
    check("sort_key 排序方向正确（高分在前）", R.sort_key(big) < R.sort_key(small))

    print(f"\n通过 {PASSED}，失败 {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
