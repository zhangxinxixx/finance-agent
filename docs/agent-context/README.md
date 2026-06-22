# Agent Context Routing

本目录承接原 `AGENTS.md` 中低频、长篇、按需规则。默认不要自动读取全部文件；只在任务命中时读取对应文档。

| 文档 | 读取时机 |
|---|---|
| `hermes-governance.md` | Hermes OS、Core/Executor/Subagent、多 Agent、CodeGraph、Reasoning OS、Memory/Output Layer |
| `skill-context-routing.md` | 需要选择专项 skill，或用户讨论上下文过载、skill 默认加载、前端/报告/Agent 治理/验收技能组合 |
| `obsidian-rules.md` | 需要写入 Obsidian、版本记录、ADR、路线图、任务看板、开发日志或知识库归档 |
| `commands-and-acceptance.md` | 需要运行项目命令、Mem0 预取、测试矩阵、提交前验收或 smoke test |

原则：

- `AGENTS.md` 是默认入口；这里是按需细则。
- 普通问答、简单命令、单文件小改不读取本目录。
- 跨文件开发、架构调整、前端验收、报告产物、提交前验收按最小必要集合读取。
- 需要真正减少新会话 skill 元数据注入时，使用 `scripts/skill_context_router.py` 切换 profile。
