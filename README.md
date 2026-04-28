# Memlink Shrine

> **不是 memory 引擎，而是 memory 引擎之上的统一驾驶舱。**
> 引擎可以换，驾驶舱不换。

Memlink Shrine 是一个面向 **判断延续** 而非单纯 **知识调用** 的 AI 记忆编排框架。它本身不存储向量，也不重新发明召回算法——它把 mem0、OpenMemory、VCP、Zep 这类 memory 引擎当作可热插拔的"动力源"，自己专心做一件事：

**为每个用户或团队定义一套属于自己的写入准则、召回路径与治理标准，并让任何 memory 引擎按这套标准为他们工作。**

如果说 mem0、OpenMemory、VCP 是不同型号的引擎，那么 Memlink Shrine 是装在它们上面的驾驶舱、仪表盘和换挡系统——决定 **什么值得记、按什么角度记、什么时候召回、走哪条路径**。

---

## 为什么需要它

这套系统的起点不是技术问题，是一个观察：

> RAG 把过去的资料调回来了，但没有把过去的判断路径一起带回来。
> 资料被找到了，结果被找到了——但通往结果的那条路：为什么放弃了 A 方案、为什么在第三次沟通后改变方向、为什么当时看似合理的判断后来被推翻——这些并不会被一起召回。

举个例子。一个设计团队上次为类似客户做了 A 方案。一年后同类客户再次出现，RAG 把 A 方案调回来——但当时为什么从 B 转 A、设计负责人对这次转向有什么保留意见、B 方案在另一类场景下其实更优……这些**判断路径**都没回来。后来者只能继承结论，无法延续判断。

Memlink Shrine 试图保留的不是"上次用了什么"，而是"上次为什么这样选、放弃过什么、为什么放弃"——也就是 **整条攻略** 而非 **最终答案**。

完整的设计哲学背景见两篇文章：

- 《从工具使用到生态建设：企业 AI 落地的认知基础与阶段路径》（[人人都是产品经理](https://www.woshipm.com/ai/6373495.html)）
- 《从知识调用到判断延续：企业 AI 在 RAG 之后的结构缺口与路径辨析》（人人都是产品经理）

---

## 它和 mem0 / OpenMemory / VCP 是什么关系

**不是替代关系，是上下层关系。**

| 层 | 它解决的问题 | 代表项目 |
|---|---|---|
| 引擎层（动力源） | 把记忆存进去、找回来 | mem0, OpenMemory, VCP, Zep, Letta |
| **编排层（驾驶舱）** | **按用户标准决定写什么、怎么写、什么时候召回、走哪条路径** | **Memlink Shrine** |

Memlink Shrine 通过两个 Protocol 把引擎层抽象出来（见 `memlink_shrine/contracts.py`）：

- `MemlinkWriteAdapter` —— 任何能存的引擎都可以挂上来
- `MemlinkRecallDelegate` —— 任何能召回的引擎都可以挂上来

当前已实现的适配器：

- **OpenMemoryAdapter** —— 读写 OpenMemory 原始记忆层
- **VcpBridgeWriteAdapter** —— 向 VCP 命名空间写入结构化桥接文件
- **VcpRecallDelegate** —— 用 VCP 自身召回逻辑作为候选源
- **LocalCatalogRecallDelegate** —— 不依赖外部引擎的本地兜底召回

切换引擎只需要改 `MEMLINK_SHRINE_RECALL_DELEGATE` 和 `MEMLINK_SHRINE_WRITE_ADAPTERS` 两个环境变量。新增引擎只需要实现两个 Protocol。

---

## 默认内核：四条不可妥协的设计主张

驾驶舱可以让用户自定义任何细节，但内核里有四条主张是这套框架的 **签名**——也是它和"通用记忆中间件"的根本区别。

### 1. 三角色分工

每条记忆的产生由三个独立角色协作完成：

- **知情者模型 / 协作模型**（在场知情者）：判断这次对话该不该写、写哪几点、姿态和情绪轨迹是什么。它最懂现场，不替底层联想做召回。
- **治理馆员模型**（默认 Gemini）：负责四摘要、标签、领域包和质量校验——它最懂标准。**但它不替知情者决定写入意图，也不替 VCP 做联想图。**
- **联想引擎 / VCP**（或 OpenMemory / mem0 / 其他）：负责底层联想、相近记忆激活和召回——它最懂底层。

三者各做各的事，互不僭越。代码里就是 `gemini_librarian.py` + `session_auto_writer.py` + `recall_delegate.py` / `vcp_bridge.py` 的清晰分工。

### 2. 残影写入：不是遗产，是痕迹

`memlink_shrine/writing_spec.py` 里写得很硬：

> 残影不是遗产：写入时保存痕迹，召回时才生成当下意义。
>
> 死路、推翻、放弃、犹豫和高成本试错必须允许被保存，用来避免成功学式幸存者偏差。

每条记忆都包含四个不同视角的摘要：

| 摘要 | 回答的问题 | 视角 |
|---|---|---|
| **事实摘要** | 发生了什么、做了什么决定、出现了什么结果 | 第三者客观叙述 |
| **意义摘要** | 这张卡让系统理解方式、结构、协议或路线发生了什么改变 | 系统结构视角 |
| **姿态摘要** | 这段路是怎么被走出来的：坚定推进、试探摸索、反复拉扯，还是被迫转向 | 知情者第三者观察 |
| **情绪轨迹** | 这一阶段的信心、张力、犹豫、不甘、释然如何变化 | 可观察的张力轨迹 |

这套字段不是装饰——它对应了"判断路径"四个不同的承重位。意义摘要 **不是结论**，是结构差异；姿态摘要 **不是抒情**，是路径形态；情绪轨迹 **不是文学**，是决策张力。

### 3. 三档写入：熄火 / 自动 / 被动

记忆系统不应默认一直开着。Memlink Shrine 的悬浮控火台（`shrine_overlay.py`）提供三种模式：

- **熄火**：完全不写。
- **自动**：知情者模型自行判断写入时机。
- **被动**：写入前先展示"残影草稿"，由用户在草稿箱里确认后才落库——防止闲聊被当成判断。

### 4. Souls-like 存档美学

UI 借用了 Souls 系列的"篝火 / 残影"语汇——这不是装饰。它在视觉上明确表达：**记忆是一个有仪式感的存档行为，不是聊天的副产物。** 每一次落库都是一次篝火点燃；每一张卡片都是一段残影。

---

## 单条记忆的结构

每张卡（`CatalogCard`，见 `memlink_shrine/models.py`）分为两层：

- **内容层**：`fact_summary`、`meaning_summary`、`posture_summary`、`emotion_trajectory`、`body_text`、`raw_text`
- **关系层**：`main_id`、`upstream_main_ids`、`downstream_main_ids`、`relation_type`、`topology_role`、`path_status`、`focus_anchor_main_id`、`is_landmark`

默认 brief 只使用摘要、正文层和关系层；原文层是最后一级，不进入常规路径。这是为了让"先看到通往结果的路径"成为默认行为，"看到完整原文"成为显式追问。

主 ID 默认是可读的路径码（规则在 `main_id_schema.yaml`，可被用户改写）：

```
ML-RET-M00-MN-20260414-0007
│  │   │   │  │        │
│  │   │   │  │        └── 稳定流水号
│  │   │   │  └─────────── 北京时间写入日期
│  │   │   └────────────── 角色码
│  │   └────────────────── 拓扑位置
│  └────────────────────── 子图域
└───────────────────────── 图谱域
```

---

## 查询流程

1. 用户用自然语言提问。
2. 系统读取本地目录卡，不预加载所有记忆。
3. 治理馆员模型根据标题、摘要、标签、语义维度和关系信息选择候选卡。
4. 系统补充命中卡的原点锚定和上下游 1–2 步局部脉络。
5. 默认生成 memory brief，不复制原文。
6. 用户显式追问"原文 / 全文 / 完整内容"时，再读取 OpenMemory 原文层。

---

## 主要模块

```
memlink_shrine/
├── contracts.py              引擎接口协议（Adapter / Delegate）
├── composition.py            服务组装（按配置选择引擎）
├── config.py                 运行时配置（环境变量驱动）
├── models.py                 CatalogCard 卡片结构 + 北京时区策略
├── writing_spec.py           残影写入规范（四摘要 + 核心规则 + 禁止项）
├── id_schema.py              主 ID 命名规则
├── source_rules.py           前端识别（claude_code / codex / hermes / ...）
├── db.py                     SQLite 持久化
├── gemini_librarian.py       治理馆员模型（四摘要、标签、校验）
├── session_auto_writer.py    自动残影写入（Codex 会话钩子）
├── shrine_overlay.py         Souls-like 悬浮控火台
├── direct_write.py           手动写入入口
├── recall_delegate.py        召回代理（本地兜底 + VCP 接入）
├── openmemory_adapter.py     OpenMemory 引擎适配
├── vcp_bridge.py             VCP 引擎桥接
├── service.py                服务层统一入口
├── web.py                    Web UI 修理台 / 编辑器
├── quick_start_app.py        Quick Start 独立模式
└── cli.py                    命令行
```

Web UI 是"人工修理台"，不是单纯展示页。可以修改标签、四摘要、正文、原文、主 ID、上下游主 ID、拓扑角色、路径状态和地标标记。系统默认由 AI 生成，但允许人随时纠错——不是每条都强制人工审核。

---

## 当前状态

**基础框架已经跑通**，主要功能都能演示：

- ✅ 四摘要 + 主 ID + 上下游拓扑的卡片结构
- ✅ 三角色协作写入（知情者 / 治理馆员 / 联想引擎）
- ✅ 三档写入模式（熄火 / 自动 / 被动）
- ✅ 残影草稿（写入前确认，避免闲聊污染）
- ✅ OpenMemory 与 VCP 的双向适配
- ✅ Web UI 修理台 + Souls-like 悬浮控火台
- ✅ Quick Start 独立模式（不依赖 OpenMemory / VCP）
- ⏳ UI 微调（持续迭代中）

下一步规划（不在本次落地范围）：

- 多记忆引擎并行映射
- 多人协同与异步同步留痕
- 更多 memory 引擎的官方适配（mem0、Zep、Letta）

---

## Quick Start

如果只想本地快速体验，不依赖 OpenMemory / VCP / Codex：

```powershell
.\启动Memlink Shrine Quick Start.ps1
```

或双击 `启动Memlink Shrine Quick Start.cmd`。

启动后会拉起：

- 一套独立程序与独立 SQLite（`data/memlink_shrine_quick_start.db`）
- 悬浮控火台
- Web UI 在 `http://127.0.0.1:7862`
- 内置的手动写入框（多段写入用单独一行 `---` 分隔）

完整模式（接入 OpenMemory + VCP + Codex 生命周期）见 `start_memlink_shrine_full.ps1`。环境变量见 `.env.example`。

---

## 命令行

```powershell
python -m memlink_shrine.cli init-db
python -m memlink_shrine.cli sync-openmemory --days 7
python -m memlink_shrine.cli list-cards --limit 20
python -m memlink_shrine.cli query-brief --question "回忆一下我们如何定义 Memlink Shrine"
```

---

## 时间策略

Memlink Shrine 自己产生的所有系统事件时间统一使用 **北京时间** `Asia/Shanghai`，不读取操作系统时区——因为本机时区可能为了网络环境被设置成其他地区。这是写入准则的一部分，不是配置项。

---

## 设计哲学链接

完整的产品哲学和理论背景请阅读：

1. [《从工具使用到生态建设：企业 AI 落地的认知基础与阶段路径》](https://www.woshipm.com/ai/6373495.html)
2. 《从知识调用到判断延续：企业 AI 在 RAG 之后的结构缺口与路径辨析》

第二篇里提出的"镜子与窗户"和"判断路径继承 vs 结论继承"是这个项目要解决的问题。

---

## 作者

杨晨。一个用销售背景进入 AI 产品视角的产品经理。
