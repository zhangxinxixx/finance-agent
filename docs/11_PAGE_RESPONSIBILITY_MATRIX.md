# 页面职责矩阵

> 代码基线：2026-07-21。

| 页面 | 权威输入 | 页面可以做 | 页面不能做 |
| --- | --- | --- | --- |
| Dashboard | dashboard summary、reports、strategy | 汇总与跳转 | 用行情 freshness 推断分析 freshness |
| Gold Mainlines | gold mainlines/runtime contract | 展示主线与证据 | 本地重算主线结论 |
| Rates & Dollar | macro/market/mainline read models | 展示利率美元驱动 | 生成最终交易方向 |
| Oil & Geopolitics | event/mainline read models | 展示地缘传导 | 把候选新闻当确认事实 |
| Data Ingestion | data source status/health | 测试、重试、上传 | 隐藏 stale/failure/manual-required |
| Event Flow | event/brief/report-input APIs | link、ignore、include、review | 绕过 action API 改状态 |
| Feishu Monitor | Feishu/Jin10 read models | 监控与筛选 | 把登录失败显示为“无消息” |
| Market Monitor | tickers/monitor/candles/macro | 图表和跨资产观察 | 在前端算策略或核心指标 |
| CME Options | option snapshot/decision/report | 展示墙、decision、visual | 重算 Black-76 / GEX |
| Reports | report index/detail/artifacts | 筛选、阅读、下钻 | 拼装新的报告结论 |
| Knowledge | knowledge/playbook APIs | 展示版本与关联 | 混淆知识模板和当前运行状态 |
| Scheduler | pipeline contract、runs、preflight | 展示 DAG、触发和状态 | 假定 trigger success 等于 pipeline success |
| Processing Monitor | processing trace APIs | 按链路下钻 | 替代 source trace registry |
| Review Center | review APIs | 批准、拒绝、重跑、fallback | 直接覆盖历史输出 |
| Strategy | strategy/live/shadow APIs | accepted 策略与评估 | 把 observe-only 当正式策略 |
| Settings | settings/agent/playbook APIs | 受控配置与治理 | 回显 secret、绕过审计 |
| LLM Audit | LLM audit APIs | 查看模型调用证据 | 将审计记录当市场事实 |

所有页面共同验收：路由可达、loading/error/empty 有区别、业务日期与更新时间可见、非 live 状态有明确标签、source/run/report ID 可下钻。
