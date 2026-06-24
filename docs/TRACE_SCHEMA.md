# Trace Schema

## 目标

定义 finance-agent 中所有分析产物的 **数据溯源标准**。每个报告、策略卡片、事件分析都必须记录：
- 数据从哪里来
- 数据的时间
- 经过了哪些处理步骤
- 哪些是事实数据、哪些是 LLM 推断、哪些是系统推导

## 溯源分类（DataCategory）

在系统中数据分为三类（对应 `apps.analysis.agents.schemas.DataCategory`）：

| 类别 | 枚举值 | 定义 | 示例 |
|------|--------|------|------|
| **确认数据** | `confirmed_data` | 可验证的结构化数据 | FRED API 返回值、CME PDF 字段、Jin10 K线 |
| **外部意见** | `external_opinion` | LLM / 金十 / 第三方分析内容 | Jin10 日报结论、LLM 文本分析 |
| **系统推导** | `system_inference` | 确定性 Agent 计算输出 | 实际利率 = DGS10 - T10YIE、Gamma Proxy |

**所有数据必须在 source_refs 或 DataCategory 中标注类别，不允许混淆。**

## Trace 对象规范

### 最低必填字段

```json
{
  "source_id": "string（唯一标识）",
  "source_name": "string（人类可读名称）",
  "source_type": "string（web|api|pdf|screenshot|manual_upload|agent_output|system_computed）",
  "data_date": "YYYY-MM-DD",
  "captured_at": "ISO 8601 timestamp",
  "used_for": ["string（在分析中的用途）"]
}
```

### 完整字段（推荐）

```json
{
  "source_id": "fred_dgs10_20260615",
  "source_name": "FRED DGS10",
  "source_type": "api",
  "data_date": "2026-06-15",
  "captured_at": "2026-06-15T12:00:00Z",
  "endpoint": "https://fred.stlouisfed.org/api/v2/series/DGS10",
  "url": "https://fred.stlouisfed.org/series/DGS10",
  "file_path": null,
  "sha256": null,
  "status": "confirmed_data",
  "used_for": ["10Y nominal yield", "opportunity cost calculation"],
  "warnings": []
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source_id` | string | ✅ | 唯一标识，建议格式：`{source}_{series}_{date}` |
| `source_name` | string | ✅ | 人类可读名称，如 "FRED DGS10" |
| `source_type` | string | ✅ | 数据类型：`api` / `pdf` / `screenshot` / `manual_upload` / `agent_output` / `system_computed` |
| `data_date` | string | ✅ | 数据对应的业务日期 (YYYY-MM-DD) |
| `captured_at` | timestamp | ✅ | 数据获取时间 (ISO 8601) |
| `endpoint` | string | ❌ | API 端点或文件路径 |
| `url` | string | ❌ | 公开可访问的原始数据 URL |
| `file_path` | string | ❌ | 归档文件的相对路径 |
| `sha256` | string | ❌ | 文件完整性校验 |
| `status` | string | ❌ | `confirmed_data` / `external_opinion` / `system_inference` |
| `used_for` | list | 推荐 | 在分析中的用途列表 |
| `warnings` | list | ❌ | 数据质量警告（PRELIM、缺失字段等） |

## 不同来源的 source_refs 写法

### API 来源（FRED、Treasury、Fed）

```json
{
  "source_id": "fred_dgs10_20260615",
  "source_name": "FRED DGS10",
  "source_type": "api",
  "data_date": "2026-06-15",
  "captured_at": "2026-06-15T12:00:00Z",
  "endpoint": "https://fred.stlouisfed.org/api/v2/series/DGS10",
  "url": "https://fred.stlouisfed.org/series/DGS10",
  "used_for": ["10Y nominal yield"]
}
```

### PDF 来源（CME Daily Bulletin）

```json
{
  "source_id": "cme_bulletin_20260615_section64",
  "source_name": "CME Daily Bulletin Section 64",
  "source_type": "pdf",
  "data_date": "2026-06-15",
  "captured_at": "2026-06-15T09:30:00Z",
  "file_path": "raw/cme/daily_bulletin/2026-06-15/Section64_2026-06-15_abc123.pdf",
  "sha256": "abc123...",
  "url": "https://www.cmegroup.com/daily_bulletin/current/Section64_Metals_Option_Products.pdf",
  "used_for": ["gold options OI", "gamma calculation"],
  "warnings": ["PRELIM data"]
}
```

### 截图来源（TradingView、用户上传）

```json
{
  "source_id": "tradingview_xauusd_15m_20260615_1200",
  "source_name": "TradingView XAUUSD 15m",
  "source_type": "screenshot",
  "data_date": "2026-06-15",
  "captured_at": "2026-06-15T12:00:00Z",
  "file_path": "screenshots/2026-06-15/xauusd_15m.png",
  "used_for": ["technical structure", "15m execution"]
}
```

### Jin10 文章来源

```json
{
  "source_id": "jin10_article_221600",
  "source_name": "金十数据 黄金日报 2026-06-15",
  "source_type": "web",
  "data_date": "2026-06-15",
  "captured_at": "2026-06-15T12:00:00Z",
  "url": "https://xnews.jin10.com/article/221600",
  "used_for": ["daily gold outlook", "sentiment assessment"],
  "warnings": ["external_opinion — 非官方数据"]
}
```

### Agent 推断来源

```json
{
  "source_id": "agent_macro_liquidity_output_20260615",
  "source_name": "macro_liquidity_agent 输出",
  "source_type": "agent_output",
  "data_date": "2026-06-15",
  "captured_at": "2026-06-15T12:05:00Z",
  "used_for": ["macro regime classification"],
  "warnings": ["system_inference — 非原始数据"]
}
```

### 手工计算来源（系统推导）

```json
{
  "source_id": "computed_real_yield_10y_20260615",
  "source_name": "10Y 实际利率（计算值）",
  "source_type": "system_computed",
  "data_date": "2026-06-15",
  "captured_at": "2026-06-15T12:00:00Z",
  "used_for": ["real yield analysis"],
  "warnings": ["DGS10 - T10YIE, system_computed"]
}
```

## 系统中 source_refs 的流转路径

```text
┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────┐
│ Collector │───→│ Analysis     │───→│ Report       │───→│ API       │
│ (raw)     │    │ Snapshot     │    │ Renderer     │    │ Response  │
│           │    │ / AgentOutput│    │              │    │           │
│ source_   │    │ .source_refs │    │ .source_refs │    │ Traceable │
│ refs: []  │    │ (完整列表)    │    │ → "分析溯源"  │    │ Response  │
└──────────┘    └──────────────┘    └──────────────┘    └───────────┘
                                                              │
                         ┌────────────────────────────────────┘
                         ▼
                  ┌──────────┐
                  │ DB       │
                  │ source_  │
                  │ refs     │
                  │ (JSONB)  │
                  └──────────┘
```

每一步必须 **追加** source_refs，不得覆盖或丢弃上游的 source_refs。

## 报告中「分析溯源」的输出格式

所有 Markdown/HTML 报告必须在末尾包含 `## 分析溯源 / 数据来源` 节，使用固定表格格式：

```markdown
## 分析溯源 / 数据来源

| 来源类型 | 来源名称 | 数据日期 | 获取时间 | 用途 |
|----------|----------|----------|----------|------|
| API | FRED DGS10 | 2026-06-15 | 12:00 UTC | 10Y 名义利率 |
| PDF | CME Bulletin S64 | 2026-06-15 | 09:30 UTC | 期权 OI 和 Gamma |
| Web | 金十 黄金日报 | 2026-06-15 | 12:00 UTC | 市场情绪评估 |
| Agent | macro_liquidity_agent | 2026-06-15 | 12:05 UTC | 宏观 regime |
| 计算 | 10Y 实际利率 | 2026-06-15 | 12:00 UTC | DGS10 - T10YIE |
```

## source_refs 校验规则

生成报告时必须校验以下规则：

| 规则 | 说明 | 违规处理 |
|------|------|----------|
| 非空 | source_refs 不能为空 | 报告标记 `missing_source` |
| 日期完整 | 每个 ref 必须有 `data_date` | 标记 `incomplete_date` |
| 类别标注 | 每个 ref 建议有 `status` 字段 | 缺失时降级为 warning |
| 用途标注 | 每个 ref 建议有 `used_for` 字段 | 缺失时不阻塞 |
| 外部意见标识 | Jin10/LLM 来源必须标注 `external_opinion` | 必须修复 |
| 无重复 | 同一 source_id 不重复出现 | 去重 |
| 上游继承 | 不能丢弃 collector/agent 传入的 refs | 必须追加，不能覆盖 |

## 与 DB Schema 的对应关系

以下 DB 表包含 `source_refs` 字段（JSONB）：

| 表 | 字段 | 说明 |
|----|------|------|
| `analysis_snapshots` | `source_refs` | 分析快照的数据来源 |
| `agent_outputs` | `source_refs` | 每个 Agent 输出的数据来源 |
| `final_analyses` | `source_refs` | 最终分析报告的数据来源 |
| `report_items` | `source_refs` | 报告产物的数据来源 |
| `task_steps` | `source_refs` | 任务步骤的数据溯源 |
| `playbooks` | `source_refs` | 策略卡片的数据来源 |
| `review_items` | `source_refs` | 审查项的原始数据来源 |

## API 响应中的 source_refs

前端通过 `TraceableResponse` 获取溯源信息：

```json
{
  "run_id": "run-20260615-001",
  "snapshot_id": "XAUUSD:2026-06-15:analysis",
  "data_status": "live",
  "source_refs": [
    {
      "source_id": "fred_dgs10_20260615",
      "source_name": "FRED DGS10",
      "source_type": "api",
      "data_date": "2026-06-15",
      "captured_at": "2026-06-15T12:00:00Z",
      "endpoint": "https://fred.stlouisfed.org/api/v2/series/DGS10",
      "url": "https://fred.stlouisfed.org/series/DGS10"
    }
  ],
  "artifact_refs": [],
  "warnings": []
}
```

前端 `FASourceTraceBadge` / `SourceTracePanelFrame` 组件消费该数据。

## 实施优先级

- **P0**：所有 Agent 输出必须包含 source_refs（已有 `AgentOutput.source_refs` 字段约束）
- **P0**：报告渲染必须输出「分析溯源」节（已在 `final_report.py` 实现）
- **P1**：为 source_refs 添加 `status` 字段标注数据类别
- **P1**：为源数据添加完整性校验（缺少字段时标记 warning）
- **P2**：前端统一溯源面板的 UI 交互
