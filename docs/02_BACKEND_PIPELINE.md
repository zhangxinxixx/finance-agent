# 后端主链

## 固定主链

```text
api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output
```

这是项目边界，不应新增第二套任务主脑。

## API

文件：

- `apps/api/main.py`
- `apps/api/schemas/*.py`
- `apps/api/services/*.py`

职责：

- 暴露只读 API、少量受控写 API。
- 创建 `TaskRun` / `TaskStep`。
- 派发 premarket worker。
- 返回 dashboard、reports、source trace、settings、review、strategy、agent 等 read model。

重要 API：

- `POST /api/tasks/premarket`
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/source-trace/{snapshot_id}`
- `GET /api/reports/{report_id}`
- `GET /api/dashboard/summary`
- `GET /api/data-sources/status`
- `GET /api/reviews`
- `GET /api/strategy-cards/latest`

## Scheduler

文件：

- `apps/scheduler/runner.py`
- `apps/scheduler/jin10_refresh.py`

当前实现：

- `dispatch_premarket_task()` 通过后台线程调用 `apps.worker.runner.run_premarket()`。
- FastAPI lifespan 中用 APScheduler 运行 Jin10 cache refresh 和每日 premarket。

风险：

- 当前是 MVP 单实例调度，尚未引入独立队列或分布式 worker。
- 任务派发成功不等于 pipeline 成功，验收必须看 TaskRun/TaskStep 和 artifact。

## Worker

文件：

- `apps/worker/runner.py`
- `apps/worker/pipelines/macro.py`
- `apps/worker/pipelines/cme.py`

当前 canonical step：

```text
macro_collect
macro_feature
cme_download
cme_parse
cme_ingest
option_wall
report_render
strategy_card
```

状态：

- CME 和 macro step 已接入真实 pipeline。
- 非 CME/macro step 在 loop 内仍会先按 stub success 处理。
- analysis snapshot、C4 agents、final report、strategy card 在 step loop 后统一执行。

后续建议：

- 将 `analysis_snapshot`、`c3_agents`、`final_report`、`strategy_card`、`report_index` 等拆成显式 `TaskStep`。
- 每一步写入 `input_refs`、`output_refs`、`source_refs`、`artifact_refs`。

## Collectors

目录：

- `apps/collectors/`

已发现领域：

- CME Daily Bulletin
- FRED
- Fed
- Treasury
- DXY
- technical / XAUUSD price
- positioning
- Jin10

职责：

- 拉取官方或市场源数据。
- 保存 raw 或返回 collector result。
- 输出 source refs。

## Parsers

目录：

- `apps/parsers/`

示例：

- `apps/parsers/cme/pdf_parser.py`
- `apps/parsers/macro/models.py`
- Jin10 parsed artifacts under `storage/parsed/jin10`

职责：

- 把 raw PDF/JSON/API response 转成结构化 rows / points。
- 不补造缺失数据。

## Features

目录：

- `apps/features/`

示例：

- `apps/features/macro/snapshot.py`
- `apps/features/options/calibration.py`

职责：

- 生成 deterministic feature snapshots。
- 期权墙、宏观指标等在这里计算，不能放到前端。

## Analysis

目录：

- `apps/analysis/`

已实现：

- `apps/analysis/snapshots/builder.py`
- `apps/analysis/agents/*.py`
- `apps/analysis/strategy/card.py`
- `apps/analysis/macro/*`
- `apps/analysis/options/*`
- `apps/analysis/jin10/*`

职责：

- 生成统一 analysis snapshot。
- 运行 domain agents 和 coordinator。
- 生成 final analysis result 和 strategy card。

## Renderer

目录：

- `apps/renderer/`

示例：

- `apps/renderer/markdown/final_report.py`
- `apps/renderer/html/options_visual.py`

职责：

- 把结构化模型渲染为 Markdown / HTML。
- 不做数据采集和策略计算。

## Output

目录：

- `apps/output/`

示例：

- `apps/output/artifacts.py`
- `apps/output/final_report.py`
- `apps/output/feishu.py`

职责：

- 统一 artifact 路径。
- 写入 final report / strategy card。
- 提供可复用外部输出工具。

## 验收建议

后端主链修改后至少验证：

- `rtk uv run pytest tests/api -q`
- `rtk uv run pytest tests/features -q`
- 相关 parser/collector regression
- `GET /api/health`
- `POST /api/tasks/premarket` 后检查 TaskRun、TaskStep、storage artifact
