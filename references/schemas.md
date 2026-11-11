# 数据结构 —— 想直接改文件时看这个

状态根目录：`~/.study-os/`（可用环境变量 `STUDY_OS_HOME` 覆盖）

```
~/.study-os/
├── profile.json
├── mistakes/index.json
├── cards/cards.json
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
{"第一章 向量空间": "warn", "1.1 线性无关": "ok", "1.2 基与维数": "blank"}
```
取值 `ok`（已掌握）/ `warn`（有偏差）/ `blank`（空白）。键必须与 `outline.json` 的 `title` **完全一致**，否则点不亮。

### quiz.json —— 检索题
```json
[{"node": "1.1 线性无关", "q": "线性无关的定义是什么？", "a": "若 k1v1+…+knvn=0 只有零解。"}]
```
`node` 可以是节标题（精确匹配）或章标题（其下所有节都会显示这道题）。

---

## logs/sessions.jsonl

每行一个事件，追加写入，不重写：

```json
{"ts":"2026-11-11T10:30:00","kind":"grade","id":"c-20261111-001","q":4,"interval":1}
{"ts":"2026-11-11T10:35:00","kind":"mistake_add","id":"M-20261111-001","cause":"M"}
```

`kind` 取值：`grade` / `mistake_add` / `mistake_retest`。
用途：算"同类问题连续通过第 3 次"（毕业条款）。**这是唯一能证明闭环在运转的证据**——没有这个文件，就还是 v2 那种"假装备份"。

---

## 手工修复

- **卡片全丢** → 检查 `cards.json` 是否为合法 JSON；`_common.load` 在解析失败时会自动备份成 `*.bak-<时间戳>`，不会静默覆盖
- **导图点不开某节点** → 99% 是 `mastery.json` 或 `quiz.json` 的键与 `outline.json` 的 `title` 不一致（多一个空格也算）
- **想重置** → 删掉 `~/.study-os/` 重跑 `init.py`。**删之前先备份 `mistakes/` 和 `cards/`**，那两个是真资产
