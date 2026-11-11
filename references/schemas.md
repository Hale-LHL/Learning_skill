# 数据结构 —— 想直接改文件时看这个

状态根目录：`~/.study-os/`（可用环境变量 `STUDY_OS_HOME` 覆盖）

```
~/.study-os/
├── profile.json
├── mistakes/index.json
├── cards/cards.json
├── resources/index.json
├── atlas/<slug>/{meta,outline,mastery,quiz}.json + atlas.html
└── logs/sessions.jsonl
```

所有 JSON 均为 **UTF-8、无 BOM、2 空格缩进**。脚本用「写临时文件 + 原子替换」落盘，中途崩溃不会产生半截文件。

---

## profile.json

```json
{
  "level": "intermediate",
  "created": "2026-11-11",
  "graduated": ["python/列表推导"],
  "illusions": [
    {"date": "2026-11-10", "topic": "概率/条件期望", "self": 4, "actual": 1}
  ],
  "notes": ""
}
```

| 字段 | 取值 | 作用 |
|---|---|---|
| `level` | `novice` / `intermediate` / `advanced` / `null` | 三轴裁决表的行。判错代价不对称，宁低勿高 |
| `graduated` | 话题字符串数组 | 已放手的话题，不再主动引导 |
| `illusions` | 记录数组 | 自评与实测差 ≥2 分的条目，出现即视为胜任错觉 |

---

## cards/cards.json

```json
[
  {
    "id": "c-20261111-001",
    "q": "矩阵可对角化的充要条件是什么",
    "a": "有 n 个线性无关的特征向量",
    "tag": "线代/特征值",
    "ef": 2.5,
    "rep": 1,
    "interval": 1,
    "due": "2026-11-12",
    "created": "2026-11-11",
    "history": [{"date": "2026-11-11", "q": 4}]
  }
]
```

| 字段 | 说明 |
|---|---|
| `ef` | easiness factor，初始 2.5，下限 1.3（SM-2 标准） |
| `rep` | 连续通过次数；未通过（q<3）重置为 0 |
| `interval` | 当前间隔天数 |
| `due` | 下次到期日，ISO 格式 |
| `history[].q` | 该次回忆评分 0–5 |

**SM-2 更新规则**（`scripts/review.py:sm2_update`）：

```
q < 3  → rep=0, interval=1
q ≥ 3  → rep=0:interval=1 / rep=1:interval=6 / else:interval*=ef
ef' = ef + (0.1 - (5-q)(0.08 + (5-q)0.02))，下限 1.3
```

`q=4` 时 ef 不变（0.1−0.1=0），这是公式本身的性质，不是 bug。

---

## mistakes/index.json

```json
[
  {
    "id": "M-20261111-001",
    "topic": "线代/特征值",
    "question": "A=[[2,1],[0,2]] 能否对角化",
    "my_work": "算出两个相同特征值 2，直接说能对角化",
    "cause": "M",
    "subcause": "P",
    "created": "2026-11-11",
    "next_due": "2026-11-13",
    "retest": {"date": null, "passed": null},
    "cards": []
  }
]
```

| 字段 | 说明 |
|---|---|
| `topic` | 用 `大块/具体` 格式，脚本按 `/` 前半段统计"反复出错的知识块" |
| `my_work` | **原始思路，不是正确答案**。这是归因的唯一证据，不许省略 |
| `cause` | 主因，七类代号之一 |
| `subcause` | 次因，可为空串 |
| `retest` | 变式验证结果。`passed: false` 意味着**归因大概率错了** |
| `next_due` | 按错因差异化排期（K=1 P=1 M=2 R=3 T=4 C=7 E=7 天） |

### 七类错因

| 代号 | 名称 | 首访间隔 | 补漏方式 |
|---|---|---|---|
| K | 知识缺口 | 1 | 回到知识点：最小示范 → 复述 → 基础题 |
| M | 概念误解 | 2 | 先破后立：讲出错误模型 → 构造荒谬推论 → 自己发现矛盾 |
| P | 程序错误 | 1 | 拆步骤定位崩点，只重练那一步 3 遍 |
| R | 表征错误 | 3 | 条件圈画训练 |
| C | 粗心 | 7 | 加检查流程，**不加题量** |
| T | 迁移失败 | 4 | 3 道结构同表面异的变式 |
| E | 元认知 | 7 | 自评-实测对账 |

---

## atlas/<slug>/

### meta.json
```json
{
  "title": "线性代数入门",
  "author": "某作者",
  "source": "D:/books/linalg.epub",
  "format": "epub",
  "chapters": 6,
  "words": 210000,
  "slug": "linalg"
}
```

### outline.json —— 扁平层级列表（不是嵌套树）
```json
[{"level": 1, "title": "第一章 向量空间", "words": 0, "file": "OEBPS/ch1.xhtml"},
 {"level": 2, "title": "1.1 线性无关", "words": 2100, "file": "OEBPS/ch1.xhtml"}]
```
`level` 为 1/2/3。`build_atlas.py` 用栈把它转成嵌套树，并让父节点字数累加子节点。
**为什么存扁平而不是嵌套**：手写和 diff 都容易，改一个标题不用处理嵌套括号。

### mastery.json —— 掌握度标记
```json
{"第一章 向量空间": "warn", "1.1 线性无关": "ok", "1.2 基与维数": "blank", "2.2 矩阵表示": "skipped"}
```
取值 `ok`（已掌握）/ `warn`（有偏差，含"改选才答对"和"蒙对"）/ `blank`（空白）/ `skipped`（用户主动跳过，**不加罚**）。键必须与 `outline.json` 的 `title` **完全一致**，否则点不亮。

### quiz.json —— 检索题（选择题 + 短答题）
```json
[{"node": "1.1 线性无关",
  "q": "「向量组线性无关」是什么意思？",
  "a": "k1v1+…+knvn=0 只有零解。",
  "correct": "B",
  "options": [
    {"k": "A", "text": "其中任意一个向量都能被其余向量线性表示出来", "cause": "K"},
    {"k": "B", "text": "k1v1+…+knvn=0 成立时，系数必须全为零", "cause": null},
    {"k": "C", "text": "向量组里没有任何两个向量是平行或共线的", "cause": "M"},
    {"k": "D", "text": "向量组里的向量个数不超过空间的维数", "cause": "T"}
  ]},
 {"node": "第一章 向量空间",
  "q": "收尾一题，没有选项：用一句话说这章解决了什么问题？",
  "a": "把「能不能凑出某个向量」变成可计算的问题。"}]
```
`node` 可以是节标题（精确匹配）或章标题（其下所有节都会显示这道题）。

| 字段 | 说明 |
|---|---|
| `options` | 省略 = **无选项短答题**（章末必留一道，识别≠回忆） |
| `correct` | 正确项的 `k`，必须是 `options` 里存在的字母 |
| `options[].cause` | **干扰项专属**，取 `K/M/P/R/T`；正确项填 `null`。选错靠它定位错因 |
| 规则与质检 | 见 `book-atlas.md` §2.3，跑 `scripts/check_quiz.py <slug>` 验 |

---

## resources/index.json —— 资源锚点

```json
[{"id": "R-20261111-001",
  "topic": "线代/特征值",
  "url": "https://www.bilibili.com/video/BV1aW411Q7x1",
  "bvid": "BV1aW411Q7x1",
  "platform": "bilibili",
  "kind": "video",
  "title": "《线性代数》教学视频  宋浩老师（2024年更新）",
  "author": "宋浩老师官方",
  "pubdate": "2018-08-21",
  "view": 77860091, "like": 1517140, "favorite": 1425332,
  "coin": 1268421, "reply": 34620, "danmaku": 1782501,
  "note": "特征值在第 42 讲左右，前 5 分钟在复习行列式",
  "evergreen": true,
  "status": "ok",
  "checked": "2026-11-11",
  "created": "2026-11-11"}]
```

| 字段 | 说明 |
|---|---|
| `kind` | `video` / `primary`（官方文档、论文原文、教材原书）/ `blog` |
| `view` `like` `favorite` `coin` | **B 站接口返回的真实值，禁止手填**。取不到就不入库 |
| `pubdate` | 发布时间。非 `evergreen` 且超过 4 年会提醒可能过时 |
| `evergreen` | 内容不随版本变化（数学原理、算法思想）。工具/API/考纲类不要标 |
| `note` | **写第几讲/几分几秒**。只写"讲特征值"没用，用户点进去面对 60 集会直接关掉 |
| `status` | `ok` / `blocked`（页面在但拒脚本）/ `unreachable`（本次连不上）/ `dead`（404，永不推荐） |
| `checked` | 上次探活日期。超过 30 天 `pick` 会降权并标注未复检 |

**为什么数字必须来自接口**：AI 写 BV 号是幻觉高发区。实测随手编的 `BV1xx411c7ZZ` 能查到
一个真实但完全无关的视频——格式对、能打开、内容不相干，比 404 更有害。
所以 `add` 时对 B 站链接强制走 `api.bilibili.com/x/web-interface/view`，取不到直接失败。

裁决门槛（播放 ≥5 万、收藏/点赞 ≥0.6、收藏/播放 ≥1%）是**工程阈值，无实证依据**，
见 `evidence.md` §4。改门槛就改 `scripts/resources.py` 顶部的常量，不要散落在文档里。

---

## logs/sessions.jsonl

每行一个事件，追加写入，不重写：

```json
{"ts":"2026-11-11T10:30:00","kind":"grade","id":"c-20261111-001","q":4,"interval":1}
{"ts":"2026-11-11T10:35:00","kind":"mistake_add","id":"M-20261111-001","cause":"M"}
{"ts":"2026-11-11T10:41:00","kind":"quiz_answer","slug":"linalg","node":"1.1 线性无关","q_index":2,"choice":"C","correct":"B","cause":"M","revised":true,"lucky":false}
```

`kind` 取值：`grade` / `mistake_add` / `mistake_retest` / `quiz_answer` / `resource_add`。
`quiz_answer` 字段含义：`choice` 用户选的字母；`cause` 该干扰项的错因；`revised` 是否改选后答对；`lucky` 答对但说不出为什么（蒙对）。**改选答对记 `warn`，蒙对也记 `warn`，都不记 `ok`。**
用途：算"同类问题连续通过第 3 次"（毕业条款）。**这是唯一能证明闭环在运转的证据**——没有这个文件，就还是 v2 那种"假装备份"。

---

## 手工修复

- **卡片全丢** → 检查 `cards.json` 是否为合法 JSON；`_common.load` 在解析失败时会自动备份成 `*.bak-<时间戳>`，不会静默覆盖
- **导图点不开某节点** → 99% 是 `mastery.json` 或 `quiz.json` 的键与 `outline.json` 的 `title` 不一致（多一个空格也算）
- **想重置** → 删掉 `~/.study-os/` 重跑 `init.py`。**删之前先备份 `mistakes/` 和 `cards/`**，那两个是真资产
