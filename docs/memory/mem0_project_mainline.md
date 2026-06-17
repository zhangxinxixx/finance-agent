# Mem0 在项目开发主线中的定位

## 目标

Mem0 在本项目中仅用作 **项目开发主线记忆层 + 临时 run-staging 缓冲层**，不替代 Obsidian、Git、Postgres 或 MinIO。

## 职责边界

### Mem0 负责

| 类别 | 示例 |
|------|------|
| 项目定位 | "这是一个面向黄金/白银/BTC 的金融分析中台" |
| 当前阶段 | "当前执行 Phase 1 布局重构" |
| 架构原则 | "Agent 只负责归因和报告，不替代指标计算" |
| 优先级 | "P0 页面：总览、数据接入、研究工作台、报告、任务" |
| 卡点 | "本地分析效果不及 ChatGPT 会话分析" |
| Agent 约束 | "每次只执行一个 Phase，不允许全量重构" |
| 用户反馈 | "Dashboard 必须突出研究流程" |
| 错误模式 | "不要一次性提交超过 5 个文件" |

### Mem0 不负责

| 内容类型 | 正确存储位置 |
|---------|------------|
| 完整代码 | Git |
| 完整文档 / 设计 | Obsidian (`~/wiki/Finance-Agent-Knowledge-Vault`) |
| 完整报告 | `outputs/` + Postgres |
| 原始数据 | MinIO / `storage/raw/` |
| 结构化数据 | Postgres / ClickHouse |
| 开发日志 | Obsidian 或 `hermes/staging/run-staging-YYYYMMDD/` |
| 临时会话摘要 / 待整理记录 | Mem0 `run_id=run-staging-YYYYMMDD` 或 repo `hermes/staging/run-staging-YYYYMMDD/`，每日整理后再决定是否提升 |

## 记忆分类

所有项目主线记忆必须使用以下类型之一：

```
project_vision         — 项目定位
project_principle      — 项目原则
current_phase          — 当前阶段
current_priority       — 当前优先级
architecture_decision  — 架构决策
frontend_direction     — 前端方向
backend_direction      — 后端方向
agent_rule             — Agent 规则
blocker                — 当前卡点
next_action            — 下一步动作
error_pattern          — 错误模式
user_feedback          — 用户反馈
```

## 实体层级自动分类

每条对话/记忆写入时自动按内容分类到四层之一：

| 层级 | 实体作用域 | 写入内容 | 信号词示例 |
|------|-----------|---------|-----------|
| **user** | `user_id` | 用户偏好、习惯、环境 | "我习惯"、"以后默认"、"记住" |
| **app** | `app_id` | 项目规则、架构约束 | "禁止"、"不允许"、"架构决策"、"主链" |
| **agent** | `agent_id`（必要时同时带 `app_id`） | Agent 职责边界 | "risk_agent"、"只负责"、"agent 规则" |
| **run** | `run_id` | 临时会话、助手摘要、待整理记录 | "本轮记录"、"会话摘要"、"待整理"、"staging" |
| *(skip)* | — | 临时数据、市场报价 | "价格"、"帮我查"、"bug" |

**关键约束**：app / agent / run 级写入使用 Mem0 原生顶层参数，不能把作用域模拟到 metadata；app / agent / run 级写入不传 `user_id`。
**自动写入**：Hermes Mem0 插件 `sync_turn()` 每轮对话自动分类写入。
**半自动写入**：用户消息含 `写入mem0` / `作为规则` / `架构决策` 时触发。
**跳过写入**：市场数据、临时查询、错误堆栈、代码块、SQL。

### run-staging 临时桶规则

run-staging 是“待整理缓冲层”，不是长期记忆层：

- Mem0 临时桶：`run_id=run-staging-YYYYMMDD`。
- repo 临时目录：`hermes/staging/run-staging-YYYYMMDD/`。
- 每天 08:00 整理前一天 run-staging；如果机器没开，下一次 Hermes cron / 开机补跑任务应先整理缺失日期，再新建当天 staging。
- 整理时只把稳定规则、用户偏好、项目架构约束、Agent 职责边界提升到 user/app/agent；普通任务进度、一次性摘要、市场临时数据丢弃或保留在 `daily-closeout.md` 待人工确认。
- 当天 run 桶测试必须优先使用 `--dry-run` 或测试专用 run_id，避免误清空真实当天记录。

推荐命令：

```bash
# 预览整理某天，不写入、不删除
uv run python scripts/mem0_daily_consolidate.py --date YYYYMMDD --dry-run

# 确认后整理并清空该 run 桶
uv run python scripts/mem0_daily_consolidate.py --date YYYYMMDD
```

## 写入原则

1. **只写摘要**：每条记忆不超过 2000 字符，不写完整日志。
2. **必加类型**：每条记忆必须有明确的 `memory_type`。
3. **必加标签**：使用 `tags` 字段标注领域（如 `frontend`、`phase1`、`dashboard`）。
4. **写前校验**：通过 `MemoryPolicy.validate_record()` 校验。

## 读取方式

### Hermes 自动检索

- 会话启动：`prefetch()` 自动拉取 top 5 记忆注入系统提示
- 主动检索：`mem0_search()` / `mem0_profile()` 工具

### 项目代码检索

```python
# MemoryRouter：自动推断 agent + 三段检索
from apps.analysis.memory.memory_router import MemoryRouter
router = MemoryRouter()
ctx = router.retrieve("CME 期权分析", task="cme 期权持仓报告")
prompt_block = router.format_for_prompt("当前任务", agent_id="risk_agent")

# 触发判断
from apps.analysis.memory.memory_policy import should_retrieve, should_write
should_retrieve("项目架构决策")  # True
should_write("后续默认如此")      # True
```

### 获取项目状态快照

```python
state = mainline.get_current_state()
# {"current_phase": [...], "blocker": [...], ...}
```

## 与 Obsidian 协作

- Obsidian 更新重要文档后 → 提取摘要写入 Mem0
- Mem0 中发现过期或错误记忆 → 标记后同步到 Obsidian 复盘文档
- 完整文档永远以 Obsidian 为准，Mem0 仅做快速上下文注入

## 文件结构

```
apps/analysis/memory/
├── __init__.py                 # 模块入口
├── memory_types.py             # 枚举和数据模型
├── memory_service.py           # Mem0 SDK 封装
├── memory_policy.py            # 写入策略校验 + 实体分类 + 触发判断
├── memory_router.py            # Agent 推断 + 三段检索 + 去重
├── mem0_client.py              # 统一 client 入口（读 env 创建 MemoryClient）
└── project_mainline.py         # 项目主线管理器

scripts/
└── mem0_daily_consolidate.py    # 每日 run-staging → user/app/agent 整理提升

~/.hermes/hermes-agent/plugins/memory/mem0/
└── __init__.py                 # Hermes Mem0 插件（内联实体分类 + sync_turn 改造）

hermes/memory/
├── project_mainline_seed.md    # 种子数据（10条初始记忆）
└── memory_update_log.md        # 记忆更新日志

docs/memory/
└── mem0_project_mainline.md    # 本文档
```

## 分类函数同步

`classify_entity()` 有两份实现，词表需保持同步：

| 位置 | 文件 |
|------|------|
| 项目层 | `apps/analysis/memory/memory_policy.py` |
| Hermes 插件层 | `~/.hermes/hermes-agent/plugins/memory/mem0/__init__.py`（内联） |

修改分类规则时两处一起改。
