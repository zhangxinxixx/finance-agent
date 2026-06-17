# finance-agent 文档索引

本目录记录当前 `finance-agent` 的真实工程结构、架构边界、页面职责、数据模型、报告系统、溯源链路和后续规划。

这些文档以当前代码为准，不以历史计划为准。无法从代码确认的内容标记为 `NEED_VERIFY`。

## 快速入口

- [00_PROJECT_OVERVIEW.md](00_PROJECT_OVERVIEW.md)：项目定位和当前状态
- [01_ARCHITECTURE.md](01_ARCHITECTURE.md)：总体架构
- [02_BACKEND_PIPELINE.md](02_BACKEND_PIPELINE.md)：后端主链
- [03_FRONTEND_PAGES.md](03_FRONTEND_PAGES.md)：前端页面职责
- [04_DATA_MODEL_AND_STORAGE.md](04_DATA_MODEL_AND_STORAGE.md)：数据模型和存储
- [05_AGENT_ARCHITECTURE.md](05_AGENT_ARCHITECTURE.md)：Agent 架构
- [06_REPORT_SYSTEM.md](06_REPORT_SYSTEM.md)：报告系统
- [07_SOURCE_TRACE_AND_RUN.md](07_SOURCE_TRACE_AND_RUN.md)：Run / Snapshot / SourceTrace
- [08_BACKEND_ROADMAP.md](08_BACKEND_ROADMAP.md)：后端改造规划
- [09_FRONTEND_ROADMAP.md](09_FRONTEND_ROADMAP.md)：前端改造规划
- [10_API_MAP.md](10_API_MAP.md)：API 映射
- [11_PAGE_RESPONSIBILITY_MATRIX.md](11_PAGE_RESPONSIBILITY_MATRIX.md)：页面职责矩阵
- [12_RISKS_AND_TODO.md](12_RISKS_AND_TODO.md)：风险与待办
- [13_NEWS_DATA_PIPELINE.md](13_NEWS_DATA_PIPELINE.md)：新闻数据源采集状态与后续流程架构
- [audit/CURRENT_PROJECT_AUDIT.md](audit/CURRENT_PROJECT_AUDIT.md)：真实代码审计
- [audit/DOCS_SELF_REVIEW.md](audit/DOCS_SELF_REVIEW.md)：文档自检
- [diagrams/DIAGRAMS_INDEX.md](diagrams/DIAGRAMS_INDEX.md)：Mermaid 图索引
- [dev/feishu-docs/README.md](dev/feishu-docs/README.md)：飞书云文档入口、归档清单、发布命令和 V2 工程文档中台说明

## 固定边界

- 项目不是自动交易系统。
- 当前主前端是 `apps/frontend-web/src`。
- FastAPI `/dashboard` 只是兼容跳转，不是新功能入口。
- 生产主链固定为：

```text
api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output
```

## 使用方式

后续开发前先读 `AGENTS.md`，再按任务类型读取本目录中对应文档。若文档和代码冲突，以当前代码和 `AGENTS.md` 为准。
