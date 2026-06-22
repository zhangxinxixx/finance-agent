# 新闻数据源采集与流程架构

更新时间：2026-06-12

本文记录当前新闻链已经打通的数据源、artifact、API read model、后续日报生成流程和仍需补齐的边界。结论以当前代码、测试和本地 `storage/` artifact 为准，不把历史计划或 mock 设计稿当作已接入事实。

## 1. 当前结论

新闻链已经从“单一新闻摘要”推进到“候选事件采集 -> 事件分类 -> 影响路径 -> 行情反应 -> follow-up 任务”的闭环雏形。

当前稳定可用的是：

- 官方/半官方事件源：`fed_rss`、`bea_calendar`、`eia_energy` 已有 raw/parsed artifact，并能进入新闻 feature 层。
- 免费候选新闻源：`google_news_rss`、`reuters_public_news` 已有 raw/parsed artifact。
- Jin10/Feishu 线索源：`jin10_news`、Jin10 detail page、`jin10_article_briefs` 已经接入 read model 和 Event Flow。
- 事件加工层：`event_candidates`、`impact_assessments`、`market_reactions`、`daily_market_brief` 已生成本地 artifact。
- 后续跟进层：`daily_analysis_followups` 可以创建 `daily_analysis_followup` 类型的 `TaskRun` / `TaskStep`，worker 已能展开 `detail_fetch`、`vip_browser_fallback`、`daily_analysis` 三段执行计划。

仍需明确边界：

- `gdelt_news` 采集器和冷却/read model 已实现，但当前本地数据源状态显示 raw/parsed 样本未刷新；下一步需要重新跑一次 live smoke，把最新 GDELT 样本落库。
- `reuters_public_news` 只是公开元数据候选源，来自可公开访问 metadata / Google News RSS，不是 LSEG/Reuters Connect 授权新闻流，不保存 Reuters 全文，也不绕登录。
- Jin10/Feishu 适合补充交易线索、文章摘要和报告触发，不作为单一事实终审源。
- LLM 不应直接消费几百条原始新闻；应消费去重后的事件、来源证据、行情快照和风险标记。

## 2. 已接入新闻数据源

| source_key | 当前状态 | 角色 | 已有证据 | 事实边界 |
| --- | --- | --- | --- | --- |
| `fed_rss` | ok | Fed 官方事件源 | `storage/raw/news/fed_rss/`、`storage/parsed/news/fed_rss/`、`daily_market_brief` | 只确认 Fed 官方发布/讲话/纪要事件，不替代 FRED 时间序列 |
| `bea_calendar` | ok | BEA 发布日历事件源 | `storage/raw/news/bea/`、`storage/parsed/news/bea/` | 记录 PCE/GDP 等发布时间；数据值仍走宏观链 |
| `eia_energy` | ok | EIA 能源事件源 | `storage/raw/news/eia/`、`storage/parsed/news/eia/` | 用于油价/通胀链条事件，不替代完整能源研究 |
| `google_news_rss` | ok | 免费关键词候选扫描 | `storage/raw/news/google_news_rss/`、`storage/parsed/news/google_news_rss/` | 只进入候选池，不能直接升格为 confirmed |
| `reuters_public_news` | ok | Reuters 公开元数据候选源 | collector、测试、数据源状态均已接入 | 非授权 Reuters feed；只采公开 metadata |
| `jin10_news` | ok | 中文交易线索和报告触发 | `daily_market_brief`、`jin10_article_briefs`、Event Flow read model | 辅助交易解读，重要事实需交叉验证 |
| `gdelt_news` | implemented / needs fresh sample | 全球新闻雷达 | `apps/collectors/news/gdelt.py`、GDELT cooldown/read model、测试 | 适合候选发现；当前本地样本需刷新 |
| `bls_calendar` | not_connected | BLS 发布日历 | source contract 已登记 | 后续补 raw/parsed 采集和入链 |

## 3. 已形成的 artifact

新闻链当前核心产物在 `storage/features/news/<date>/<run_id>/` 下：

| artifact | 用途 | 当前消费者 |
| --- | --- | --- |
| `event_candidates.json` | 把 raw news / calendar / report event 转成候选事件 | impact classifier、daily market brief、Event Flow |
| `impact_assessments.json` | 给候选事件绑定资产、方向、影响路径、置信度 | `daily_market_brief`、news agent、event impact agent |
| `market_reactions.json` | 绑定 XAUUSD / DXY / US10Y / WTI 等行情反应 | `daily_market_brief`、后续日报 |
| `daily_market_brief.json` | 稳定新闻主读模型，拆分 confirmed / candidate / unconfirmed | API、Event Flow、Agent 输入 |
| `report_events.json` | 从 Jin10/report 侧抽取结构化事件 | event candidates、daily brief snapshot 规划 |
| `jin10_article_briefs.json` | Jin10 文章级摘要、价值判断、follow-up 触发 | Event Flow、follow-up queue |
| `daily_analysis_triggers.json` | 日报触发器和待跟进线索 | follow-up queue |

当前 API / read model：

- `GET /api/data-sources/status`：展示数据源配置、raw/parsed/analysis_ready 状态、artifact 路径和部分运行诊断。
- `GET /api/events/flow/overview`：聚合 `daily_market_brief`、`daily_analysis_followups`、`article_briefs`。
- `GET /api/jin10/article-briefs/latest`：读取最新 `jin10_article_briefs`。
- `GET /api/news/daily-analysis-followups/latest`：读取最新待跟进日报任务。
- `POST /api/news/daily-analysis-followups/tasks`：把 follow-up 转成可追踪 `TaskRun` / `TaskStep`。

## 4. 当前处理流程

当前新闻主链按已有项目边界运行，不新增第二套任务主脑：

```text
api / scheduler
-> worker
-> collectors
-> parsers
-> features
-> analysis
-> renderer / output
```

新闻链内部拆成七段：

1. `news_collect`：采集官方事件源、免费聚合源、Reuters 公开元数据、Jin10/Feishu 线索。
2. `raw_news_items`：保存原始响应、标题、URL、发布时间、source ref 和诊断信息。
3. `parsed news`：标准化 source、query group、language、domain、published_at、raw payload。
4. `event_candidates`：按关键词、来源角色、时间、实体和主题生成候选事件。
5. `impact_assessments`：绑定影响路径和资产方向，严格保留 `verification_status`。
6. `market_reactions`：把事件与 XAUUSD、DXY、US10Y、WTI/Brent、USDJPY 等行情窗口绑定。
7. `daily_market_brief` / `daily_analysis_followups`：生成 Event Flow 和后续日报任务入口。

## 5. 事实确认与分层规则

新闻链必须保留来源分层，避免把候选线索写成确定事实。

| verification_status | 含义 | 可进入日报主结论 |
| --- | --- | --- |
| `official_confirmed` | Fed/BLS/BEA/EIA/Treasury/CME 等官方源确认 | 可以 |
| `multi_source` | 至少两个独立来源互相印证 | 可以，但需标注来源 |
| `report_derived` | 来自 Jin10 报告/文章分析 | 可以作为交易解读，不作为事实终审 |
| `single_source` | 单一候选新闻源 | 只进候选风险 |
| `unverified` | 噪声、缺少确认或来源质量不足 | 不进入主结论 |

推荐事实链：

```text
GDELT / Google News / Reuters Public Metadata 发现事件
-> Jin10 / Feishu 补充交易上下文
-> 官方源或授权通讯社确认
-> 行情快照验证市场是否响应
-> LLM 只基于结构化事件和证据写分析
```

## 6. Follow-up 任务流程

当前 follow-up 已从 read model 推进到可审计任务：

1. `daily_analysis_followups` 合并 `daily_analysis_triggers` 和 `jin10_article_briefs`。
2. `POST /api/news/daily-analysis-followups/tasks` 为待跟进项创建 `TaskRun(task_type=daily_analysis_followup)`。
3. worker 先运行 `news_followup`，把输入转成执行计划。
4. `detail_fetch` 尝试抓取详情页并生成 detail artifact。
5. 如果详情页 `readable`，跳过浏览器兜底，`daily_analysis` 保持待执行。
6. 如果详情页 `vip_locked` 或 `javascript_required`，转入 `vip_browser_fallback`，但不把失败伪装成成功。
7. 后续 `daily_analysis` 将消费详情页、报告事件、行情反应和 source refs，生成稳定日报输入。

## 7. 非交易日宏观事件影响补充报告

后续新增 `macro_event_followup` 报告族，用于非交易日把最新宏观/新闻事件与最近一个开盘日正式结论串起来。它是正式落盘的补充报告，不是新的正式综合报告。

生成边界：

- 只在非交易日生成，第一版先覆盖周末；节假日交易日历后置。
- `trade_date` 使用非交易日当天日期。
- `anchor_trade_date` 使用最近一个开盘日，锚定该日的 `final_report / strategy_card`。
- 报告只能说明“新事件对原结论的影响”，不能直接改写原 `strategy_card` 或前端主交易结论。
- 如果事件足以削弱原结论，输出 `revision_risk=needs_review` 或 `revision_risk=regenerate_on_next_open`，由人工复核或下一个开盘日正式主链处理。

输入建议：

- 最近开盘日 `final_report / strategy_card` 摘要与 source refs。
- 当天 `daily_market_brief`、`daily_analysis_followups`、`jin10_article_briefs`、`event_candidates`、`impact_assessments`、`market_reactions`。
- 最新宏观指标状态和数据源 freshness。
- 已有 Event Flow read model 中的重点事件、影响路径和行情验证。

输出建议：

```text
storage/outputs/macro_event_followup/XAUUSD/<trade_date>/<run_id>/
  source.md
  analysis.md
  report_structured.json
```

核心段落：

- `上一开盘日结论锚点`：说明 `anchor_trade_date` 和被补充的正式结论。
- `新增宏观/新闻事件`：只列结构化输入中有来源的事件。
- `影响评估`：标记强化、削弱、扰动、暂不影响。
- `下个开盘日前观察项`：事件、价位、宏观数据、市场反应。
- `改判风险`：说明是否需要人工复核或下一个开盘日重新生成正式综合报告。

## 8. 后续流程架构

下一阶段建议按下面顺序推进，避免把日报直接交给 LLM 自由发挥。

### P0 收尾

- 重新跑 GDELT live smoke，刷新 `storage/raw/news/gdelt/` 和 `storage/parsed/news/gdelt/`。
- 补 `bls_calendar` raw/parsed 采集，至少覆盖 CPI、PPI、Employment Situation、JOLTS。
- 把 `collection_diagnostics.json` 固定纳入每次新闻 run，前端 Data Ingestion 能看到失败原因、cooldown、source ref count。
- 对 `reuters_public_news` 文案保持授权边界：公开元数据候选源，不是授权 Reuters 新闻流。

### P1 日报输入快照

- 新增 `daily_brief_input_snapshot.json`。
- 输入只允许来自 `daily_market_brief`、`daily_analysis_triggers`、`jin10_article_briefs`、`report_events`、`market_reactions`。
- 输出固定包含 `report_mode`、`core_events`、`key_articles`、`market_reactions`、`risk_flags`、`source_refs`、`quality_flags`。
- `report_mode` 分为 `news_driven`、`report_driven`、`hybrid`、`empty`。

### P2 稳定日报 renderer / API

- 新增固定 Markdown renderer，不依赖外部抓取。
- 输出 `storage/outputs/daily_brief/<date>/<run_id>/daily_brief.md` 和 `.json`。
- 增加只读 API：latest、指定 date/run_id、artifact refs。
- 前端只展示 API 结果，不计算影响路径或生成结论。

### P2.5 非交易日补充分析报告

- 新增 `macro_event_followup` 输入构造器，消费最近开盘日正式结论和当天宏观/新闻 read model。
- 新增固定 Markdown/structured renderer，输出补充报告 artifact。
- 写入标准 `ReportItem / ReportArtifact`，Reports 可检索和回看。
- Dashboard `/api/dashboard/summary` 增加最新补充报告摘要，只展示补充层，不覆盖正式交易结论。
- Frontend Dashboard 标清两类日期：正式综合分析 `anchor_trade_date` 与补充分析 `trade_date`。

### P3 授权与确认层

- 如果后续采购 Reuters / Bloomberg / Refinitiv，只作为确认层或高质量事实源接入，不复用当前公开元数据名称。
- 增加 official confirmation linker：同一事件与 Fed/BLS/BEA/EIA/Treasury/CME 官方条目绑定后，再升级 `verification_status`。
- 对地缘事件保留 `need_verification=true`，直到官方或授权通讯社确认。

## 9. 验收口径

后续每个新闻链切片完成前至少给出：

- 本次涉及哪些 source_key。
- raw/parsed artifact 是否真实落盘。
- feature artifact 是否包含 `source_refs` 和 `input_snapshot_ids`。
- `GET /api/data-sources/status` 是否能显示最新状态和失败原因。
- `GET /api/events/flow/overview` 是否能消费最新 read model。
- 如果涉及 Feishu/Jin10，必须说明登录/VIP/JS 渲染失败时的降级路径。
- 如果涉及流程图发布到飞书，必须使用 Mermaid 画板小组件，不接受 Mermaid 代码块变成普通文本。
