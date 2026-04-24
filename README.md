# Memlink Shrine

Memlink Shrine 是建立在 OpenMemory 这类底层记忆库之上的“编目、脉络与调度层”。

它不替代原始记忆存储，也不强行改写原始记忆正文。它做的事是：

- 从 OpenMemory 读取原始记忆。
- 让高能力模型担任“知情馆员”，生成记忆卡。
- 将记忆卡保存到独立的本地 SQLite。
- 查询时先用标签、摘要和语义维度缩圈。
- 命中后默认只展开摘要、正文层和局部上下游脉络。
- 只有用户显式要求“原文/全文/完整内容”时，才进入原文层。

## V2 核心机制

V2 不再把旧版的“全开 / 半开 / 封闭”作为主框架。新的主框架拆成两件事：

1. 全局检索机制：决定“先想到哪条记忆”。
2. 单条展开机制：决定“想到以后先看到多少”。

这两个机制拆开后，系统可以先保证快速定位，再按用户追问逐步提升分辨率。

## 单条记忆结构

当前记忆卡分成两层：

- 内容层：`fact_summary`、`meaning_summary`、`body_text`、`raw_text`。
- 关系层：`main_id`、`upstream_main_ids`、`downstream_main_ids`、`relation_type`、`topology_role`、`path_status`、`is_landmark`。

默认 brief 只使用摘要、正文层和关系层。原文层是最后一级，不进入常规路径。

## 主 ID

默认主 ID 只是“可读路径码”，不是不可改的唯一身份。默认形式：

```text
ML-RET-M00-MN-20260414-0007
```

含义：

- `ML`：图谱域。
- `RET`：子图域。
- `M00`：位置。
- `MN`：角色码。
- `20260414`：北京时间写入日期。
- `0007`：稳定流水号。

默认规则写在 `main_id_schema.yaml`，后续用户可以按自己的业务习惯调整。

## 查询流程

1. 用户用自然语言提问。
2. 系统读取本地目录卡，不预加载所有记忆。
3. Gemini 根据标题、摘要、标签、语义维度和关系信息选择候选卡。
4. 系统补充命中卡的原点锚定和上下游 1 到 2 步局部脉络。
5. 默认生成 memory brief，不复制原文。
6. 用户显式追问“原文/全文/完整内容”时，再读取 OpenMemory 原文层。

## UI 定位

Web UI 是“人工修理台”，不是单纯展示页。人可以修改：

- 标签和语义维度。
- 事实摘要和意义摘要。
- 正文层与原文层。
- 主 ID、上游主 ID、下游主 ID。
- 拓扑角色、路径状态、关系类型和地标标记。

系统默认由 AI 自动生成，但允许人随时纠错，不强制每条人工审核。

## 命令

```powershell
python -m memlink_shrine.cli init-db
python -m memlink_shrine.cli sync-openmemory --days 7
python -m memlink_shrine.cli list-cards --limit 20
python -m memlink_shrine.cli query-brief --question "回忆一下我们如何定义 Memlink Shrine"
```

## 时间策略

Memlink Shrine 自己产生的系统事件时间统一使用北京时间 `Asia/Shanghai`。这不是读取电脑系统时区，因为电脑可能为了网络环境设置成其他时区。


