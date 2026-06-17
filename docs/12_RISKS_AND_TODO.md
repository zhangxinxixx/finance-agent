# 风险与待办

## 高优先级

1. C4 pipeline 未完全 Step 化
   - 现状：`strategy_card` 在 step order 中存在，但真实 final report / strategy card 写入在 worker 末尾 C4 pipeline。
   - 风险：Agent Tasks 中 run step 和真实 artifact 生成不完全一一对应。
   - 待办：拆出 `analysis_snapshot`、`c3_agents`、`final_report`、`strategy_card`、`report_index` TaskStep。

2. Alembic migration 缺失
   - 现状：`database/migrations/versions/` 无实际版本文件，当前依赖 `ensure_*_tables()`。
   - 风险：生产/长期本地数据库结构不可复盘。
   - 待办：稳定 schema 后补 migrations，并限制 runtime DDL 范围。

3. 报告 artifact 标准化未完全验证
   - 现状：Report API 已存在，但不同报告族是否都具备 `source.md`、`analysis.md`、`visual.html`、`report_structured.json` 需验证。
   - 风险：Report Detail 展示不一致。
   - 待办：逐 report family 做 artifact registry regression。

4. mock/fallback 需要强标记
   - 现状：前端 `src/mocks/` 存在多个 mock 文件，部分 adapters 有 fallback。
   - 风险：用户误把 mock 当 live。
   - 待办：统一 DataStatus 和 UI badge。

## 中优先级

5. SourceTrace 覆盖 legacy artifacts
   - 现状：SourceTrace API 已存在，legacy report 可能没有完整 snapshot_id。
   - 待办：为 legacy report 增加兼容 source trace 或显式 unavailable。

6. DataSourceStatus 枚举收敛
   - 现状：模型状态字段存在，但文档规划的 `LIVE / STALE / PARTIAL / FALLBACK / OFFLINE / MOCK / MANUAL_REQUIRED` 需要和历史值兼容。
   - 待办：后端 enum / frontend badge / docs 三方一致。

7. Agent fact review / synthesis 主链地位待验证
   - 现状：模块和 API 存在。
   - 待办：确认是否每次 premarket run 必经，并写入 TaskStep/artifact。

8. API legacy 与 read model 并存
   - 现状：`/api/strategy-card*` 与 `/api/strategy-cards*`、final report legacy 和 reports API 并存。
   - 待办：保留兼容入口，文档和前端默认使用新 read model。

## 低优先级

9. 页面拆 Tab 后的组件边界
   - Market Monitor、CME Options、Settings 还可进一步拆分。
   - 避免先做视觉重构，应先稳定 API contract。

10. 文档持续更新
   - 本轮文档是 2026-06-09 基线。
   - 后续改主链、API、页面职责、报告 artifact 时必须同步更新对应文档。
