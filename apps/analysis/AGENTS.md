# Analysis Module Instructions

## 模块定位

`apps/analysis/` 是 finance-agent 的分析引擎，负责将采集到的原始数据转化为结构化分析结论。所有分析 Agent 只做 **只读推断**，不修改原始数据。

## 关键目录

```
apps/analysis/
  agents/         # Agent 实现（macro_liquidity, cme_options, risk, synthesis...）
  macro/          # 宏观分析（regime, conclusion, summary, full_report）
  jin10/          # 金十日报分析（agent_analysis, visual_report, daily_report）
  strategy/       # 策略卡片（card, schemas）
  snapshots/      # 分析快照构建
  memory/         # 记忆系统（Mem0 客户端/路由/策略）
  prompts/        # LLM prompt 模板
```

## Agent 契约（强制）

每个 Agent 必须遵守 `apps.analysis.agents.schemas.AgentOutput` 输出契约：

```python
class AgentOutput(BaseModel):
    version: str
    agent_name: str
    module: str
    snapshot_id: str
    input_snapshot_ids: dict[str, Any]
    bias: AgentBias          # BULLISH / BEARISH / NEUTRAL / MIXED / UNAVAILABLE
    confidence: float         # 0.0 - 1.0
    key_findings: list[str]
    risk_points: list[str]
    watchlist: list[str]
    invalid_conditions: list[str]
    summary: str
    source_refs: list[dict]   # 必须包含所有上游数据引用
    evidence_items: list[dict] # 结构化证据因子：factor/direction/strength/confidence/freshness/source_tier 等
    status: AgentStatus       # SUCCESS / PARTIAL / UNAVAILABLE / FAILED
    # P4-05 fields:
    market_phase: str | None  # rate_pressure / transition_release / trend_tailwind / liquidity_crunch / monetary_credit_repricing / unavailable
    regime_drivers: dict | None
```

**不允许任何 Agent 输出格式偏离此契约。**

## Agent 清单

| Agent | 文件 | 职责 | 数据类型需要 |
|-------|------|------|-------------|
| `macro_liquidity_agent` | `agents/macro_liquidity.py` | 宏观利率/流动性分析 + regime 分类 | DGS10, DGS2, T10YIE, DXY, SOFR, EFFR, IORB, TGA, RRP |
| `cme_options_agent` | `agents/cme_options.py` | CME/COMEX 黄金期权墙分析 | CME Daily Bulletin Section 64/65 |
| `risk_agent` | `agents/risk.py` | 风险环境评估 | HY OAS, VIX, 地缘事件 |
| `market_odds_agent` | `agents/market_odds.py` | 市场方向概率 | 多维度指标 |
| `synthesis_agent` | `agents/synthesis.py` | 最终合成 | 所有上游 AgentOutput |
| `fact_review_agent` | `agents/fact_review.py` | 事实核查（规则引擎）| 数据完整性 |
| `event_impact_agent` | `agents/event_impact.py` | 事件影响分析 | 新闻/事件流 |
| `news_agent` | `agents/news.py` | 新闻语义分析 | GDELT / Jin10 / Reuters |

## CME 期权分析专项规则

### 计算优先级

1. **Black-76 真实 Gamma / GEX**（需要 IV、settlement、T、F 完整）
   - `GEX = Gamma × OI × 100 × F² × 0.01`
   - Call GEX 为正，Put GEX 为负
   - `NetGEX = CallGEX - PutGEX`
2. **Gamma Proxy**（仅字段缺失时）
   - `Gamma Proxy = OI × |Delta| × (1 - |Delta|)`
   - 必须标注「使用 Proxy，非真实 Gamma」

### 墙位判断

| 类型 | 定义 |
|------|------|
| 活墙 (Active) | OI 最大 + OI 增长 + Block/PNT 活跃 |
| 静墙 (Static) | OI 大但无新增 + 成交量低 |
| 换手墙 (Roll) | OI 从一个 strike 向相邻 strike 迁移 |

### 必须输出

1. Call Wall / Put Wall（strike + OI + GEX + 类型）
2. Gamma Flip（NetGEX = 0 的价格）
3. Pin 区域
4. 3 支撑 / 3 阻力
5. Block/PNT 机构信号
6. 数据状态（PRELIM / FINAL / MISSING）
7. 分析溯源

### 禁止事项

- 不混淆 OI 墙 / Gamma 墙 / 成交墙
- 不把 Proxy 当真实 Gamma
- 不对 PRELIM 数据做确定性判断
- 不遗漏字段缺失说明

## 宏观分析专项规则

### 分析框架

1. **实际利率** = DGS10 - T10YIE（核心驱动，与金价反向）
2. **美元** = DXY（主定价货币）
3. **流动性** = TGA + RRP + 准备金（资金环境）
4. **利率走廊** = SOFR / EFFR / IORB（政策姿态）

### Regime 分类（market_phase）

| 类别 | 条件 | 对黄金影响 |
|------|------|-----------|
| `rate_pressure` | 实际利率上行 + 美元强 | 压力 |
| `transition_release` | 利率见顶 + 美元转弱 | 释放 |
| `trend_tailwind` | 实际利率下行 + 流动性宽松 | 顺风 |
| `liquidity_crunch` | 10Y 接近/突破压力区 + DXY 急涨 + 流动性未放松 | 先防踩踏 |
| `monetary_credit_repricing` | 收益率/美元不弱但黄金仍强 | 货币信用重估 |
| `unavailable` | 数据不足 | 无法判断 |

## 数据要求

### 缺失数据处理

| 等级 | 处理方式 |
|------|----------|
| **核心字段缺失** | Agent 返回 UNAVAILABLE |
| **辅助字段缺失** | Agent 返回 PARTIAL + 标注缺失项 |
| **全部可用** | Agent 返回 SUCCESS |

### source_refs 继承

每个 Agent 必须：
1. 保留输入端 snapshot 中的 `source_refs`
2. 追加自己的计算步骤到 `source_refs`
3. 标注数据类别（confirmed_data / external_opinion / system_inference）
4. 对会参与 confidence / quality gate / source trace 的结论，保留结构化 `evidence_items`

## LLM 调用规范

- 所有 LLM 调用通过 `apps.llm.gateway.LLMGateway`
- 不允许绕过 gateway 直接调 OpenAI
- prompt 模板放 `apps/analysis/prompts/`
- LLM 输出必须标注为 `external_opinion`

## 测试要求

- 每个 Agent 必须有单元测试（`tests/analysis/`）
- 测试覆盖：正常输入 / 缺失数据 / 边界条件 / 不变性（不修改入参）
- 测试必须验证 AgentOutput schema 完整性
- 新 Agent 上线前必须通过全部 regression 测试

## 验证方式

- `uv run pytest tests/analysis/ -q` 必须全部通过
- 新 Agent 输出的 `source_refs` 必须包含上游引用
- `confidence` 必须在 0.0-1.0 范围内
- `bias` 不为 None（UNAVAILABLE 除外）
