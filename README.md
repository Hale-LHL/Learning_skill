# study-os

> 一个给 AI 学习助手用的技能包：把「问一句答一句」变成有数据、有排期、能被考试检验的学习闭环。

适用于 WorkBuddy / Claude Code 这类支持 Skill（`SKILL.md`）的 agent 环境。

---

## 为什么做这个

大多数人做 AI 学习工具的思路是「让 AI 讲得更好」。有一组数据说这条路走不通。

2025 年 PNAS 发表的一项实验，近千名高中生随机分成三组做数学练习：

| 组 | 练习阶段表现 | 之后的闭卷考试 |
|---|---|---|
| 不用 AI | 基线 | 基线 |
| 可以直接要答案的 ChatGPT | **+48%** | **−17%** |
| 只给提示、不给答案的 AI 导师 | **+127%** | **≈ 0** |

练习时表现好得多，考试时反而更差，或者毫无进步。

还有第二个发现，我觉得比第一个更值得警惕：**学生自己感觉不出来。** 用 AI 的那两组，主观上觉得自己学得更好。

所以这个技能的设计前提是：

> **引导只是地板，不是天花板。真正的增益来自「你被考了多少次」和「什么时候再被考」。**

它做的事情不花哨：记录你的错，按遗忘曲线把它们重新递到你面前，然后看你闭卷能不能答对。

---

## 三个工作流

### 1. 错题诊断

不是讲正确解法。是先搞清楚**你为什么错**。

七类错因，处理方式彼此不通用，有时完全相反：

- **K 知识缺口** → 回去学那个知识点
- **M 概念误解** → 先破后立（直接纠正无效，错误模型会存活到考试）
- **P 程序错误** → 拆步骤，只重练崩的那一步
- **R 表征错误** → 训练条件圈画（你不是不会，是没看见）
- **C 粗心** → 加检查流程，**不加题量**（刷会做的题零收益）
- **T 迁移失败** → 换变式，别刷同类
- **E 元认知** → 自评与实测对账

最关键的一条分辨：**粗心 vs 误解**。换数字重做一次，做对是粗心，还是错同一个地方是误解。把误解当粗心处理，你会刷一百道题把错误练成肌肉记忆。

跑 20 道错题之后，`stats` 会告诉你错因分布——它告诉你该改什么习惯，而不是该刷多少题。

### 2. 电子书结构化

EPUB 用标准库直接解析（zip + XHTML），不需要装任何东西。PDF 需要 PyMuPDF，没装的话可以手动给目录，正文按需喂。

重点不是提取，是**顺序**，而且分两条路：

```
要「学会」  →  一章一章过：一次一题、每题四个选项  →  答错先反问不给答案  →  章末一道无选项短答  →  最后才给导图
要「拿材料」→  直接生成三件套（结构笔记 / 地图 / 对照表）+ 五项校验 + 头部声明「这是速览不是学会」
```

**为什么默认用选择题**：让你每章口述三百字，第二轮你就懒得打字了。改成四个选项，输入成本从"一段话"降到"一个字母"，而诊断力反而更强——**干扰项是按错因（概念误解 / 知识缺口 / 迁移失败 / 表征错误）设计的，你选错我就知道该补哪个**，不用再追问一轮。

代价我也写在明处：多选题练的是**认得**，不是**想得起**。所以每章最后一道题没有选项，必须自己说一句话；`check_quiz.py` 还会检查"某章是不是全是选择题"，是就报警。

反过来的做法（你发一本书，我吐一张漂亮的全书导图）收益接近零。Karpicke & Blunt 2011 在 *Science* 上直接对比过：检索练习组的延迟测验成绩显著优于概念图组，而概念图组事后自我感觉更好。

**图是题目来源，不是阅读材料。** 演示页在 [`tests/demo/线代入门-知识地图.html`](tests/demo/线代入门-知识地图.html)，点左边节点就能看到可点的选择题。

### 3. 引导式答疑

不直接给答案，但也不是无脑反问。

一张三轴裁决表决定所有情况：问题类型（查事实 / 概念 / 解题 / 情绪）× 你的水平（新手 / 进阶 / 熟练）。

- 给零基础的人反问是伤害：「梯度下降是什么」回答「你先说说你的理解」，等于把门关上
- 给熟练的人示范也是伤害：他会的你重复一遍，他只会走神
- 不确定水平时按低一档处理，估错的代价不对称

事实性问题直接答，但**必须附来源**。机制性问题不给结论，让你先猜一个，我指出哪条证据支持或反驳。

### 4. 外部讲解（贯穿上面三个，不是第四个工作流）

书上的讲法不合口味是真痛点，所以答完之后可以附一条外部讲解（B 站视频 / 个人博客 / 官方文档）。

但这件事踩在 AI 最容易出错的地方上：**编链接**。所以我把它做成了不许编的流程，而不是加一句"请注意准确性"。

实测过一个例子：随手编的 BV 号 `BV1xx411c7ZZ` 去查，B 站接口真的返回了一个视频——标题是「ウサウサvs荒巻」，跟线性代数毫无关系。**格式对、能打开、内容不相干**，这比 404 更有害。

所以规则是：搜索 → 入库（`resources.py` 强制走接口取真实播放/收藏/点赞）→ 核对返回的标题 → `pick` → 才能出现在对话里。取不到数据就不入库，宁可不给。

筛选不用"感觉不错"，用三个能算的数（都是**工程阈值，没有实证依据**）：

| 判据 | 门槛 | 挡什么 |
|---|---|---|
| 播放量 | ≥ 5 万 | 个人练习、搬运残片 |
| **收藏 / 点赞** | ≥ 0.6 | 娱乐向内容（点赞远多于收藏） |
| **收藏 / 播放** | ≥ 1% | 搬运号、切片号（播放高但没人存） |

收藏/点赞这一条是整套判据里最有用的：知识类内容观众"留着以后用"才收藏，娱乐内容点赞多但很少收藏。标杆数据：宋浩《线性代数》播放 7786 万、收藏 142 万、点赞 152 万，收藏/点赞 0.94。

**时机比选哪条更重要。** 出题时给链接等于把题废了，用户还在想的时候给等于替他思考。默认只在**答完之后**给，一次最多 2 条，并且必须写清位置（第几讲、几分几秒）——只说"这个视频讲特征值"，用户点进去面对 60 集会直接关掉。

最后一句要说实话：视频是**被动接收**，性质接近"重看"，不在高效用清单里。它的定位是跨过某个具体理解障碍，然后回去继续闭卷检索，不是学习方式本身。**链接是止痛药，不是营养。**

---

## 快速开始

```bash
git clone https://github.com/<你的用户名>/study-os.git
```

把 `study-os` 目录放进你的 skills 目录：

- WorkBuddy：`~/.workbuddy/skills/study-os`
- Claude Code：`~/.claude/skills/study-os`

然后：

```bash
python scripts/init.py              # 初始化 ~/.study-os
python scripts/review.py due        # 看今天要复习什么
python scripts/mistake.py add       # 录一道错题（交互式）
python scripts/mistake.py stats     # 看你的错误画像
python scripts/resources.py add --topic "线代/特征值" \
    --url "https://www.bilibili.com/video/BV1aW411Q7x1" --note "第 42 讲" --evergreen
python scripts/resources.py pick --topic 线代   # 挑出能推荐的（不合格的不出现）
```

需要 Python 3.9+，**所有脚本只用标准库**，不需要 pip install。（PDF 提取是可选的例外。）

Windows 上如果 `python` 不在 PATH：

```bash
C:/Users/<你>/AppData/Local/Programs/Python/Python3xx/python.exe scripts/init.py
```

---

## 它怎么保证自己不是在自嗨

三个客观指标，都落盘，不靠感觉：

1. **闭卷抽测得分** —— 每次 `grade` 记 0–5 分，进 `logs/sessions.jsonl`
2. **变式验证通过率** —— 错题修复后做变式题，`retest --pass/--fail`。通过率低于 50% 说明补漏没做到位，或者归因错了
3. **自评与实测的差值** —— 差值 ≥2 分记入 `profile.json` 的 `illusions`，之后同类内容一律降一档

第 3 条是防「胜任错觉」的。PNAS 那篇研究里最麻烦的不是成绩差，是人不知道自己差。

---

## 设计上的一些取舍

**为什么用 SM-2 而不是 FSRS**：FSRS 更好，但它需要大量复习记录来拟合参数，冷启动阶段无效。SM-2 参数少、可解释、第一天就能用。等你的 `cards.json` 有几百条记录，换 FSRS 才划算。

**为什么主 SKILL.md 压到 250 行以内**：SKILL.md 每次触发都全量加载。规则写太厚会挤占上下文、稀释注意力，各条规则还会互相竞争优先级。细节全部推到 `references/`，按需读。（早期版本想压到 180 行，但加入"测量外部锚点"和"防弃用规则"之后实际是 241 行——这两个部分比省 token 重要。）

**为什么导图零外部依赖**：不用 markmap / mermaid 的 CDN。离线能开、断网能开、发给别人也能开。原生 `<details>` 就够折叠了。

**我明确没有证据支持的几条规则**（写在 `references/evidence.md` 里）：

- 「有效挣扎 5/15 分钟」是工程经验值，没有实验说必须是 5 分钟
- 「提示阶梯恰好 4 层」是折中，层数没有实验依据
- 「错因差异化初始间隔」是推理，没查到针对错因分型的间隔实验

这些是**可以调的旋钮，不是定理**。如果你觉得不合适，改就是了。

---

## 目录

```
study-os/
├── SKILL.md                      主入口（246 行，含三轴裁决表与外部锚点规则）
├── references/
│   ├── core-rules.md             句式库（可直接抄的话术）
│   ├── mistake-workflow.md       错题七类归因与补漏
│   ├── book-atlas.md             电子书双模式流程
│   ├── resource-anchors.md       外部讲解：时机、门槛、防编造流程
│   ├── evidence.md               证据底账（含置信度分级）
│   └── schemas.md                数据格式
├── scripts/
│   ├── init.py                   初始化
│   ├── review.py                 SM-2 复习调度
│   ├── mistake.py                错题库与错误画像
│   ├── extract_book.py           EPUB/PDF → 结构
│   ├── check_quiz.py             选择题质检（选项规则可执行版）
│   ├── resources.py              资源锚点库（B 站数据走接口，不手填）
│   └── build_atlas.py            结构 → 可交互 HTML
├── tests/
│   ├── make_sample_epub.py       测试用 EPUB 生成器
│   ├── sample_quiz.json          符合规则的题库样例（跑 check_quiz.py 全过）
│   ├── test_resources.py         资源裁决逻辑测试（18 项，不联网）
│   └── demo/                     生成好的知识地图样例（可直接打开，含可点选项）
├── tools/
│   └── gh_tunnel.py              受限网络下访问 GitHub 的本地隧道（见 docs/04）
└── docs/
    ├── 01-research-and-plan.md            调研与方案抉择
    ├── 02-diagnosis-learning-coach-v2.md  上一版的问题诊断
    ├── 03-self-review.md                  第三方视角自审与据此的修订
    ├── 04-github-access.md                连不上 GitHub 时怎么办
    └── 05-book-atlas-two-modes-plan.md    啃书双模式的方案与实施状态
```

> 如果你在国内网络环境下 `git clone` 或 `push` 报 TLS 错误、证书错误，直接看
> [`docs/04-github-access.md`](docs/04-github-access.md)——那多半不是你的配置问题，
> 是 DNS 解析到的 IP 被阻断，换一个官方 IP 就能通。

---

## 已知限制

- **不能替代你自己投入的时间**。一本 300 页的书要真学会，你还是得花 3–6 小时。这个工具的作用是把这些时间花在有反馈的地方，不是压缩成 10 分钟。
- **自评数据不可靠**，所以系统不信任自评。但如果用户持续谎报 `grade` 分数，整个闭环就失效了。这是它对你唯一的要求：别骗它。
- **EPUB 解析只在"规范 EPUB"上验证过**。我的测试样本是自己造的（`<h1>`–`<h4>` 标记标题、标准 OPF、spine 顺序正确）。真实电子书常见的问题是：标题用 `<div class="h1">` 而非 `<h1>`、OPF 路径不规范、spine 顺序错乱。遇到这些，`extract_book.py` 可能提到 0 个标题然后报错。**报错是设计行为（不会给你一个残缺的目录树冒充成功），但请别把"支持 EPUB"理解成"能处理任何 EPUB"。**
- **PDF 提取能力有限**。扫描版需要 OCR，不在范围内。没装 PyMuPDF 时只能手动提供目录。
- **选择题模式是性价比折中，不是最优解**。它把每个知识点的收益打了折（识别 ≠ 回忆），换来的是"你真的会一章一章走完"。不嫌打字的话，把 `quiz.json` 里的 `options` 删掉，就退化成简答题——收益更高，摩擦更大。这个开关故意留着。
- **错因归因需要判断力**。脚本只提供分类框架，判对判错靠对话质量。判错了，`retest --fail` 会提醒你回去重判。
- **单人本地工具，没有并发保护**。所有命令是「读—改—写」，没有文件锁。如果同时跑两个命令改同一份 JSON，后写的会覆盖先写的。单人使用不会遇到，多开 agent 时要注意。
- **资源门槛挡不住「讲得热闹但讲错了」**。播放量、收藏比只能筛掉搬运号和娱乐向内容，判断不了内容是否正确。质量最终只能靠人看两分钟。另外 B 站接口随时可能限流或改结构，届时 `resources.py add` 会**直接失败**而不是退回手填数字——这是有意的设计。
- **中文优先**。句式库和话术都是中文写的，英文环境下语气会不太对。

---

## 证据

关键文献（详细标注见 `references/evidence.md`，那里对每个数字标了置信度）：

- Dunlosky et al. (2013), *Improving Students' Learning With Effective Learning Techniques*, PSPI — 十种技术评级
- Karpicke & Blunt (2011), *Retrieval Practice Produces More Learning than Elaborative Studying with Concept Mapping*, Science
- Adesope et al. (2017), *Rethinking the Use of Tests*, RER — 检索练习元分析
- Cepeda et al. (2006), *Distributed practice in verbal recall tasks*, Psychological Bulletin
- Brunmair & Richter (2019), *Similarity matters: A meta-analysis of interleaved learning*, Psychological Bulletin
- VanLehn (2011), *The Relative Effectiveness of Human Tutoring, Intelligent Tutoring Systems, and Other Tutoring Systems*, Educational Psychologist
- PNAS (2025), 生成式 AI 无护栏使用对学习的影响

`references/evidence.md` 里明确区分了「一手文献」「二手转述」「我的工程判断」三档。拿这些数字去写论文前，请自己去核对原文。

---

## English

A skill package for AI learning assistants. Turns one-off Q&A into a measurable loop: diagnose mistakes by root cause, schedule reviews with SM-2, and verify with closed-book tests.

The premise comes from a 2025 PNAS study: students using a plain chatbot scored 48% better in practice but **17% worse on the exam**; a hint-only tutor improved practice by 127% with **zero** exam gain. Guidance alone stops the bleeding but adds nothing. The gain comes from retrieval and spacing.

Three workflows: mistake diagnosis (7 root-cause categories), book structuring (EPUB/PDF → interactive map, where the map is a question bank, not reading material), and guided Q&A (three-axis decision table; never quiz a beginner).

Python 3.9+, standard library only. Non-commercial license.

---

## License

**非商业使用许可（Non-Commercial License）** — 个人学习、教学、科研用途可免费使用、修改、分发。**未经作者事先书面认可，任何组织或个人不得将本作品用于商业用途**（出售、订阅收费、嵌入付费产品/服务、广告变现等）。

商业使用授权逐案审批：通过 GitHub Issue 联系 [@Hale-LHL](https://github.com/Hale-LHL)。

Non-commercial use, modification and redistribution are free for personal learning, teaching and research. **Commercial use is prohibited without prior written approval from the author** (case-by-case grant via GitHub Issue). See [LICENSE](LICENSE) for full terms; the Chinese text prevails.
