# Tool Registry

## 目标

记录 finance-agent 系统中所有可用的工具、Agent、脚本和 API 端点。每个工具需要说明：用途、触发条件、输入输出、不适用场景。本文档从现有 Skill 路由和脚本体系中沉淀而来。

## 工具分类

```text
web.*       — 网络搜索与抓取
data.*      — 数据采集
parse.*     — 数据解析
compute.*   — 指标计算
agent.*     — Agent 分析
report.*    — 报告生成
code.*      — 代码修改与验证
file.*      — 文件操作
memory.*    — 记忆检索与写入
deploy.*    — 发布与同步
```

---

## web.* — 网络搜索与抓取

### web.search

- **描述**：搜索公开网页、新闻、官方数据入口
- **输入**：`query` (string), `recency` (optional), `domains` (optional)
- **输出**：`results` (list of {title, url, snippet})
- **使用时机**：信息可能变化、用户要求最新数据、需要查找官方来源
- **不使用时机**：用户只要求解释已有文本

### web.fetch

- **描述**：抓取指定网页或报告正文
- **输入**：`url` (string)
- **输出**：`{title, text, published_at, source_url}`
- **使用时机**：已有明确 URL、search 返回了目标页面
- **不使用时机**：无已知 URL、需要登录的页面

---

## data.* — 数据采集

### data.macro.snapshot

- **描述**：抓取并标准化宏观指标快照
- **输入**：`date` (string), `indicators` (list of codes)
- **输出**：`{as_of, indicators: {DGS10: {value, change_1w}, ...}}`
- **实现**：`apps/analysis/macro/` + OpenBB / FRED Collector
- **使用时机**：黄金日报、市场监控

### data.cme.download

- **描述**：下载 CME Daily Bulletin PDF
- **输入**：`section_file` (string, default: Section64)
- **输出**：`CmeRawFile {report_date, raw_path, sha256, source}`
- **实现**：`apps/collectors/cme/downloader.py`
- **使用时机**：CME 期权分析、每日自动化采集

### data.jin10.fetch

- **描述**：从 Jin10 MCP 获取快讯、行情、日历、K 线
- **输入**：`report_type` (daily/weekly), `date`
- **输出**：`{quotes, calendar, flash, articles}`
- **实现**：`apps/collectors/jin10/` + Jin10 MCP server
- **使用时机**：黄金日报、事件流、行情更新

### data.news.collect

- **描述**：采集新闻（Reuters, Fed RSS, BEA, BLS, EIA, GDELT）
- **输入**：`source` (string), `date_range`
- **输出**：`list of NewsItem`
- **实现**：`apps/collectors/news/collector.py`
- **使用时机**：事件流分析、宏观监控

---

## parse.* — 数据解析

### parse.cme.pdf

- **描述**：解析 CME Daily Bulletin PDF 提取期权明细
- **输入**：`file_path` (string), `contract_months` (list)
- **输出**：`{options_table, parse_warnings}`
- **实现**：`apps/parsers/cme/` (PyMuPDF)
- **使用时机**：CME PDF 上传后

### parse.jin10.article

- **描述**：解析金十文章（HTML → Markdown + 图片）
- **输入**：`article_id` (string)
- **输出**：`{markdown, images, metadata}`
- **实现**：`apps/parsers/jin10/`
- **使用时机**：Jin10 日报采集

---

## compute.* — 指标计算

### compute.options.gamma

- **描述**：计算 CME 黄金期权的真实 Gamma / GEX / Gamma Flip
- **输入**：`options_rows` (list), `F` (futures_price), `r` (rate)
- **输出**：`{gamma_by_strike, gex_by_strike, net_gex, gamma_flip}`
- **算法**：Black-76
- **使用时机**：CME 期权分析
- **降级策略**：字段缺失 → Gamma Proxy

### compute.macro.real_yield

- **描述**：计算 10Y 实际利率 = DGS10 - T10YIE
- **输入**：`dgs10` (float), `t10yie` (float)
- **输出**：`real_yield_10y` (float)
- **使用时机**：每次宏观分析

---

## agent.* — Agent 分析

### agent.macro.liquidity

- **描述**：宏观利率 + 流动性分析 + regime 分类
- **输入**：`analysis_snapshot` (dict)
- **输出**：`AgentOutput {bias, confidence, market_phase, regime_drivers}`
- **实现**：`apps/analysis/agents/macro_liquidity.py`
- **Skill**：`gold-daily-analysis`

### agent.cme.options

- **描述**：CME 黄金期权墙结构分析
- **输入**：`options_snapshot` (dict)
- **输出**：`AgentOutput {call_wall, put_wall, gamma_flip}`
- **实现**：`apps/analysis/agents/cme_options.py`
- **Skill**：`cme-options-analysis`

### agent.synthesis

- **描述**：汇总所有上游 Agent 输出为最终结论
- **输入**：`list[AgentOutput]`
- **输出**：`AgentOutput {bias, confidence, summary}`
- **实现**：`apps/analysis/agents/synthesis.py`

### agent.fact.review

- **描述**：事实核查（规则引擎，不做 LLM 推断）
- **输入**：`analysis data` (dict)
- **输出**：`review_result {supported, partially_supported, unsupported, contradicted}`
- **实现**：`apps/analysis/agents/fact_review.py`

---

## report.* — 报告生成

### report.generate.markdown

- **描述**：生成 Markdown 格式分析报告
- **输入**：`snapshot_data`, `agent_outputs`, `source_refs`
- **输出**：`{report_path, report_id}`
- **实现**：`apps/renderer/markdown/`
- **使用时机**：所有报告类任务

### report.generate.json

- **描述**：生成 JSON 格式的结构化报告
- **输入**：同上
- **输出**：`{json_path, report_id}`
- **实现**：`apps/renderer/json/`

### report.generate.html

- **描述**：生成 HTML 可视化报告
- **输入**：同上
- **输出**：`{html_path, report_id}`
- **实现**：`apps/renderer/html/`

### report.trace

- **描述**：生成报告溯源记录
- **输入**：`sources` (list), `model_steps` (list), `generated_at`
- **输出**：`{trace_id, trace_file}`
- **规范**：`docs/TRACE_SCHEMA.md`
- **使用时机**：所有报告类任务（必须）

---

## code.* — 代码修改与验证

### code.read

- **描述**：读取代码文件并理解上下文
- **输入**：`file_path`, `offset`, `limit`
- **使用时机**：所有代码修改前（必须先读）
- **反模式**：不读文件直接改

### code.patch

- **描述**：小步替换代码（str_replace 模式）
- **输入**：`file_path`, `old_string`, `new_string`
- **输出**：unified diff
- **纪律**：最小 diff，不做整文件重写

### code.verify.lint

- **描述**：Run lint
- **命令**：`ruff check .` (Python) / `npm run lint` (前端)
- **使用时机**：所有代码修改后

### code.verify.test

- **描述**：Run tests
- **命令**：`uv run pytest -q` (Python) / `npm run build` (前端)
- **使用时机**：所有代码修改后

### code.verify.build

- **描述**：Run build
- **命令**：`cd apps/frontend-web && npm run build`
- **使用时机**：所有前端修改后

---

## file.* — 文件操作

### file.create

- **描述**：创建新文件
- **输入**：`path`, `content`
- **规则**：
  - 报告放 `storage/outputs/`
  - 临时文件放 `tmp/`
  - 不创建文件到 `raw/` / `parsed/`（只读目录）
  - 文件命名含日期和主题

### file.archive

- **描述**：归档文件到 `storage/raw/` 或 `storage/parsed/`
- **输入**：`file_path`, `archive_dir`
- **使用时机**：采集器下载完成后

---

## memory.* — 记忆检索与写入

### memory.search

- **描述**：检索历史项目记忆、用户偏好、分析规则
- **输入**：`query` (string)
- **输出**：`memories` (list)
- **实现**：Mem0 / Obsidian
- **使用时机**：用户说「继续」「沿用」「按之前规则」

### memory.write.rule

- **描述**：写入长期规则到 Mem0
- **输入**：`rule_type`, `content`, `scope`
- **使用时机**：用户明确说「记住这个规则」

### memory.sync.obsidian

- **描述**：同步报告到 Obsidian vault
- **输入**：`vault`, `path`, `content`
- **使用时机**：报告生成后

---

## deploy.* — 发布与同步

### deploy.feishu.doc

- **描述**：发布分析报告到飞书文档
- **输入**：`markdown_content`, `doc_title`
- **输出**：`{document_id, url}`
- **实现**：`scripts/publish_feishu_docs.py` + Lark MCP

### deploy.feishu.section

- **描述**：更新飞书知识库的特定 section
- **输入**：`section_name`, `markdown_content`
- **输出**：`{node_token, url}`
- **实现**：`scripts/publish_feishu_section.py`

---

## 工具使用规则

### 组合使用模式

```text
黄金日报：memory.search → data.macro.snapshot → data.jin10.fetch
  → agent.macro.liquidity → agent.cme.options → agent.synthesis
  → report.generate.markdown → report.trace → memory.sync.obsidian

CME 分析：data.cme.download → parse.cme.pdf → compute.options.gamma
  → agent.cme.options → report.generate.markdown → report.trace

前端重构：code.read → code.patch → code.verify.lint → code.verify.build
```

### 安全边界

| 工具类别 | 权限 |
|----------|------|
| web.* | 只读 GET |
| data.* | 只读，不写原始数据源 |
| parse.* | 只写 `storage/parsed/`（可写） |
| compute.* | 纯计算，无副作用 |
| agent.* | 只读推断，写 AgentOutput |
| report.* | 写 `storage/outputs/`（可写） |
| code.* | 写代码文件 + 运行验证 |
| memory.* | 读/写记忆 |
| deploy.* | 写飞书/外部（需确认） |
