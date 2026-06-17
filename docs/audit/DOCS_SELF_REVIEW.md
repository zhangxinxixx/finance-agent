# 文档自检

自检日期：2026-06-09
范围：本轮新增 `docs/` 文档和 `docs/diagrams/*.mmd`。

## 检查结果

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 是否把 legacy `apps/frontend` 误写成主线 | 通过 | 文档明确当前主线是 `apps/frontend-web/src`，且当前未发现 `apps/frontend/` 目录 |
| 是否把 `dashboard.html` 误写成新功能入口 | 通过 | 文档只说明 FastAPI `/dashboard` 为兼容跳转 |
| 是否出现代码中不存在的 API | 通过 | API 映射来自 `apps/api/main.py` 路由扫描 |
| 是否遗漏当前前端页面 | 通过 | 已覆盖 `apps/frontend-web/src/main.tsx` 中的所有 Route |
| 是否遗漏后端主链 | 通过 | 所有架构文档均保留 `api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output` |
| 是否明确报告三产物/四文件 | 通过 | 已写 `source.md`、`analysis.md`、`visual.html`、`report_structured.json`，并标注覆盖度需验证 |
| 是否明确 Agent 三层架构 | 通过 | 已区分 domain agents、fact review、synthesis，并标注主链接入状态需验证 |
| 是否明确 run/source trace 字段 | 通过 | 已覆盖 `run_id`、`snapshot_id`、`source_refs`、`artifact_refs` |
| Mermaid 图是否能识别为图 | 通过 | 7 个 `.mmd` 文件首行均为 `flowchart` |
| 是否有自动交易误导 | 通过 | 仅出现“不是自动交易系统”“不规划自动下单”“不包含自动交易/下单语义”等禁止性表述 |

## 已修正规则

- roadmap 使用“目标/后续/规划”语气，不把未完成内容写成已实现。
- 对 `fact_review_agent`、`synthesis_agent`、标准报告 artifact 覆盖、Alembic migrations 等不确定项统一标 `NEED_VERIFY`。
- 保留 legacy API，但文档默认引导到新的 `reports`、`strategy-cards`、`source-trace` read model。

## 剩余 NEED_VERIFY

1. `ReportItem` / `ReportArtifact` 是否覆盖所有报告族。
2. `source.md`、`analysis.md`、`visual.html`、`report_structured.json` 是否每个 report_id 都完整。
3. `fact_review_agent` 和 `synthesis_agent` 是否稳定进入每日 premarket 主链。
4. 生产/长期本地数据库是否需要补 Alembic migration 文件。
5. 前端 mock/fallback 使用范围需要逐 adapter 明确展示状态。

## 验证命令

已执行：

```bash
rg -n "apps/frontend 是|apps/frontend/.*主|dashboard\\.html.*新|自动交易|自动下单|下单|NEED_VERIFY|source\\.md|analysis\\.md|visual\\.html|report_structured\\.json|run_id|snapshot_id|source_refs|artifact_refs" docs/...
for f in docs/diagrams/*.mmd; do printf '%s ' "$f"; head -n 1 "$f"; done
rtk git status --short
```

说明：本轮是文档任务，未运行后端/前端业务测试，未修改业务代码。
