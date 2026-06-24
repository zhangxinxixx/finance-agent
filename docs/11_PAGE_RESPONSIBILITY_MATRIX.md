# 页面职责矩阵

| 页面 | 当前状态 | 目标职责 | 主要组件/文件 | API 依赖 | 可 mock | 验收标准 |
| --- | --- | --- | --- | --- | --- | --- |
| Dashboard | 已实现 | 总览、关键判断、报告/策略/市场入口 | `DashboardPage.tsx`、`components/dashboard/*`、`adapters/api.ts` | `/api/dashboard/summary`、`/api/reports/dates`、`/api/strategy-card/latest` | 可 fallback，但需标注 | 页面加载、数据状态可见、跳转有效 |
| Data Ingestion | 已实现/部分 fallback | 数据源健康、重试、手工上传登记 | `DataIngestionPage.tsx`、`components/data-ingestion/*`、`adapters/dataIngestion.ts` | `/api/data-sources/status`、`/api/data-status/summary`、`/api/ingestion/*` | 可先 mock | 状态区分 live/stale/fallback/mock/manual_required |
| Event Flow | 已实现 | 快讯、日历、事件流 overview 和详情 | `EventFlowPage.tsx`、`EventFlowDetailPage.tsx`、`adapters/eventFlow.ts` | `/api/events/flow/overview` | 可空态 | 事件详情可定位 source |
| Market Monitor | 已实现/部分 fallback | 市场概览、实时图、pricing chain、跨资产、事件 | `MarketMonitorPage.tsx`、`components/market-monitor/*`、`adapters/marketMonitor.ts` | `/api/market/monitor`、`/api/market/tickers`、`/api/macro/latest`、`/api/market/monitor/history` | 可 fallback | 明确行情状态和时间戳 |
| CME Options | 已实现 | 期权概览、Gamma/GEX、墙位、skew/flow、scenario、trace | `CMEOptionsPage.tsx`、`components/cme-options/*`、`adapters/cmeOptions.ts` | `/api/options/snapshot`、`/api/options/dates` | 可 fallback | 不在前端计算核心期权指标 |
| Reports | 已实现 | 报告索引、报告族筛选、进入详情 | `ReportsPage.tsx`、`adapters/reports.ts` | `/api/reports/index`、`/api/reports/dates`、Jin10/Final/Options APIs | 不建议伪造 | 每个 report 能进入 detail 或显示 unavailable |
| Report Detail | 已实现 | 可视化、LLM 分析、原文、证据、输入、溯源、版本/复盘 | `ReportDetailPage.tsx`、`adapters/reports.ts` | `/api/reports/{report_id}/*`、`/api/source-trace/by-report/{report_id}` | 仅空态 | 三产物/溯源可见或显式缺失 |
| Knowledge Base | 已实现 | 知识列表与详情 | `KnowledgeBasePage.tsx`、`adapters/knowledge.ts` | `/api/knowledge/items*` | 可空态 | 知识条目 source 和类型明确 |
| Agent Tasks | 已实现 | Run 控制台、步骤、artifact、agent inspection | `AgentTasksPage.tsx`、`AgentTaskDetailPage.tsx`、`adapters/agentTasks.ts` | `/api/runs*`、`/api/reviews`、`/api/agent-analysis/inspect` | 可 mock 开发 | 单 run 可看步骤和 artifact |
| Review Center | 已实现 | 人工复核队列和处理动作 | `ReviewCenterPage.tsx` | `/api/reviews*` | 不建议伪造 | action 后状态一致 |
| Strategy Center | 已实现 | 策略卡列表/详情/资产选择 | `StrategyPage.tsx`、`adapters/strategy.ts` | `/api/strategy-cards*` | 可 fallback | 显示非自动交易定位和 source trace |
| Settings | 已实现 | 配置中心、数据源开关、secret、Agent/Prompt governance | `SettingsPage.tsx`、`SettingsAuditPage.tsx`、`adapters/settings.ts`、`adapters/agentRegistry.ts` | `/api/settings*`、`/api/agents/*`、`/api/playbooks*` | 不建议伪造写操作 | 写操作有审计记录，secret 不明文回显 |
