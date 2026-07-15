# 前端页面职责

> 路由事实源：`apps/frontend-web/src/main.tsx`；导航事实源：`components/AppSidebar.tsx`。代码基线：2026-07-21。

## 主路由

| 路由 | 职责 |
| --- | --- |
| `/dashboard`、`/dashboard/analysis` | 总览与综合分析下钻 |
| `/gold-mainlines` | 黄金事件主线与运行编排摘要 |
| `/rates-dollar` | 利率、美元与黄金宏观关系 |
| `/oil-geopolitics` | 石油、地缘与黄金影响 |
| `/data-ingestion`、`/data-sources/:sourceId` | 数据源健康、详情、测试、重试与手工上传 |
| `/market-monitor`、`/market-monitor/odds` | 行情、跨资产监控和市场赔率 |
| `/cme-options` | CME 期权结构、decision 和可视化报告 |
| `/reports`、`/reports/:reportId` | 报告索引、artifact、输入与证据 |
| `/event-flow`、`/event-flow/:eventId` | 事件、brief、影响与市场反应 |
| `/feishu-monitor` | 飞书/Jin10 消息监控 |
| `/knowledge*` | 知识条目与详情 |
| `/scheduler` | Pipeline DAG 与运行状态 |
| `/scheduler/grid`、`/scheduler/tasks` | 调度视图与任务列表 |
| `/processing-monitor` | 按 trace/event/input/source/mainline/chain 查询加工链 |
| `/agent-tasks/:runId` | 单次 run 的步骤、日志、artifact 与 Agent 检查 |
| `/review-center` | 人工复核队列与动作 |
| `/strategy` | accepted 策略、live strategy 与 shadow evaluation |
| `/settings`、`/settings/audit` | 配置、数据源、Prompt 与变更审计 |
| `/settings/llm-audit` | LLM 调用审计 |

`/agent-tasks` 会重定向到 `/scheduler`；`/scheduler/processing-monitor` 会重定向到 `/processing-monitor`。

## 页面边界

- 页面不得自行计算策略方向、期权墙、宏观 regime 或发布资格。
- 页面必须展示 `data_status`、业务日期、生成时间和 fallback/mock/unavailable 标识。
- 写操作只能调用明确的 API action；UI 更新后应重新拉取后端状态。
- `src/mocks` 只用于演示或降级，不能伪装成 live。
- FastAPI 的 `/dashboard`、`/reports`、`/scheduler` 等是兼容跳转，不是第二套前端。

## 验证

```bash
cd apps/frontend-web
rtk npm run typecheck
rtk npm test
rtk npm run build
```
