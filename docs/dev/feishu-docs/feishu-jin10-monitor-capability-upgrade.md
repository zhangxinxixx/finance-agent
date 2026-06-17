### 能力升级：飞书金十采集与分析闭环

这次升级不是新增一条孤立链路，而是补齐“链路一：新闻事件链路”的生产能力：金十机器人消息先进入飞书群，再由系统主动拉取、去重、过滤、抓详情、生成触发器，最后进入日报分析和前端事件展示。

核心变化：

- 采集入口从手工观察升级为 `feishu_chat_pull`：按 `chat_id` 拉取群消息，保存 `message_id`、发布时间、正文、详情链接和原始 payload。
- 入库前增加业务价值判断：只有黄金、白银、原油、利率、通胀、地缘风险、CME/COMEX、金十重点文章等主线内容才触发后续分析；低价值或重复消息保留在每日清单里，但不触发日报。
- 高价值消息生成 `daily_analysis_triggers.json`：记录 `priority`、`reason_codes`、`impact_path`、`gold_impact`、`source_refs` 和单源验证状态。
- 详情页抓取升级为分层处理：公开页直接抓正文和图片；`vip_locked`、`javascript_required`、`login_required` 进入浏览器登录态兜底。
- 每天新增消息监控清单：能看到当天采集到哪些金十消息、哪些被纳入系统、哪些触发分析、哪些卡在 VIP/JS/任务失败。

能力对应关系：

- 新闻原文采集：对应原方案的 `news_collect`，升级为飞书群消息拉取、`message_id` 去重、raw/parsed artifact 留痕。
- 事件分类：对应 `event_candidates`，按黄金、原油、利率、地缘、CME、技术位等规则打标签。
- 业务过滤：对应 Review / 人工复核，先自动判定 `high_value`、`rejected`、`duplicate`，再进入人工复核。
- 分析触发：对应 `daily_market_brief`，高价值消息生成 daily analysis trigger 和 follow-up task。
- 详情内容：对应 `SourceTrace`，保存 `final_url`、`raw_html`、`raw_text`、图片资产和 VIP 状态。
- 前端展示：对应 Event Flow，增加 `/feishu-monitor` 每日清单，解释每条消息是否纳入系统。

金十 VIP 登录态不要求反复登录。系统使用本机已登录 profile：

```text
/home/zxx/.hermes/jin10_browser_profile
```

处理口径：

- requests 抓取成功：直接生成 `article_brief`，进入日报分析。
- 抓取结果为 `vip_locked` / `javascript_required` / `login_required`：自动转入浏览器 profile fallback。
- fallback 仍失败：保留为 `VIP预览`，在每日清单显示阻塞原因，不阻断其他消息。

2026-06-12 样例 `https://xnews.jin10.com/details/221732` 已被识别为高价值金十文章：

- 文章：冲突再次接近终点，但黄金的上行空间可能已不及战前。
- 分类：`vip_market_reference`。
- 标签：`gold`、`rates`、`energy`。
- 状态：已生成文章简报；当前为 `vip_locked`，需要浏览器登录态补抓全文。
- 后续：进入日报分析 follow-up 队列，并在每日监控页展示触发与阻塞状态。

Phase 3 的验收标准同步升级为：Event Flow 不只展示事件，还要能追溯到飞书消息、详情页、分析触发器、任务状态和失败原因。
