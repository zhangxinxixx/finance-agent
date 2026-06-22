# Hermes Governance Rules

仅在涉及 Hermes OS、Agent 架构、多 Agent、Reasoning OS、Memory/Output Layer 或 CodeGraph 结构查询时读取。

## 系统基本原则

- Single Decision Spine：只有 Core 进行请求路由、任务规划、任务拆解、工具/MCP 选择和验收标准判定。
- Tool is Passive Executor：Tool / MCP 只能执行，不能参与决策。
- Memory is Passive：Memory 只提供上下文参考，不驱动当前决策。
- Execution is Isolated：只有 Executor 可以真正执行工具调用。

## Core / Skill / Tool 边界

Core 禁止：

- 直接执行工具。
- 直接写入记忆。
- 修改 Skill 系统结构。

Skill 定义为无状态工作流模板，只允许提供流程建议、结构化步骤和方法模板。Skill 禁止参与路由决策、调用工具、访问记忆或改变执行优先级。

Capability Layer 统一调用接口：

```text
tool.call(name, input)
```

能力来源包括 Built-in Tools、MCP Servers 和 External APIs。MCP 是外部能力提供者，Tool 是原子执行能力。

## Execution Layer

Subagent = Pure Executor。Subagent 只执行任务步骤、调用工具、返回结果。

Subagent 禁止：

- 规划任务。
- 路由决策。
- 写入记忆。
- 选择 Skill。

执行隔离：

```text
Core     -> 只负责决策
Executor -> 只负责执行
Tool     -> 只负责动作
Memory   -> 只负责存储
Skill    -> 只负责模板
```

## 系统执行流程

```text
用户输入
  -> Core（意图识别 + 路由）
  -> Planner（任务图生成）
  -> Executor（选择执行器 -> Leaf Subagent）
  -> Capability Layer（工具 / MCP 统一调用）
  -> Memory 写入（如任务完成 / 状态变化 / 偏好更新）
  -> Output Filter（RTK -> Caveman full）
  -> 最终输出
```

## CodeGraph 规则

CodeGraph = First-class MCP。允许用途：代码结构查询、依赖关系分析、调用链追踪、影响范围分析、符号级搜索。

在有 CodeGraph 可用的情况下，代码结构探索优先使用 `codegraph_explore` / `codegraph_search` / `codegraph_callers`，替代全项目 grep + 逐文件 read。若当前会话没有 CodeGraph 工具，则使用 `rg` / `git grep` 精准定位，不做全项目无目标遍历。

## 稳定性强制约束

禁止：

- 多个决策中枢并存。
- Skill 参与路由决策。
- Tool 参与规划逻辑。
- Memory 驱动执行。
- 隐式 Agent 层级结构。
- 同一文件被多个 Agent 同时修改。
- 不经 Core 审核的自动化任务链。

## Reasoning OS

复杂推理任务（金融分析、架构判断、多步调试）必须经过：

```text
UNDERSTAND -> PLAN -> EXECUTE -> SELF_VERIFY -> OUTPUT
```

- 没有 PLAN 不允许 EXECUTE。
- EXECUTE 后必须 SELF_VERIFY。
- VERIFY 不通过则回到 EXECUTE，最多 2 个循环。
- SELF_VERIFY 不调额外模型，只做规则检查：步骤完整性、数值一致性、结论与输入是否冲突。

Scratchpad 仅在当前任务生命周期有效，任务完成后丢弃；不写入 Mem0、不写入 Obsidian。

## delegate_task 子 Agent 约束

- 子 Agent 角色强制为 `leaf`，不允许 `orchestrator` 角色嵌套决策。
- 子任务包必须写清任务目标、允许修改范围、禁止修改范围、输入文件、输出要求、验收标准、执行后报告格式。
- 默认并发上限 3 个；多 Agent 不得同时修改同一文件或同一 migration。
- 子 Agent 报告为自述信息，其声称的文件修改、命令执行、测试结果等副作用需主控二次验证。

## Output Layer

输出处理仅在后处理阶段执行，不进入 reasoning 路径：

```text
Raw Response -> RTK（CLI 输出压缩）-> Caveman full（自然语言压缩）-> Final Response
```

Caveman full 仅在达到用户 token 阈值或推理深度需求时启用；纯指令/代码任务不强制。不得压缩代码块、CLI 命令、路径、API 名、错误信息、函数签名。

## Memory Layer

两层架构：

- Session Memory：当前和关联会话的上下文注入。
- Mem0：长期语义记忆，存储偏好、约定、环境事实、经验教训。

Obsidian Vault 是外部知识归档，不参与 runtime decision。Mem0 存摘要和约束，不存完整方案或代码。若 Mem0、聊天上下文、Obsidian 入口冲突，以 Obsidian 当前入口为准。
