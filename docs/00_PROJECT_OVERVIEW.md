# 项目总览

`finance-agent` 是一个本地可运行、可追溯、可复盘的 XAUUSD / GC 金融研究中台。它用于采集官方/市场数据、解析和计算确定性特征、生成分析快照、产出报告和策略卡片，并在前端中台中提供只读分析与人工复核能力。

本项目不是自动交易系统，不规划自动下单。

## 当前定位

- 研究对象：黄金相关市场，包括 XAUUSD、GC/CME 期权、宏观流动性、Jin10 新闻/日历/行情、技术和仓位信息。
- 核心目标：把原始数据、解析结果、特征、Agent 输出、报告、策略卡片和前端展示串成可追溯链路。
- 当前阶段：MVP 到中台化过渡期，重点是可追溯底座、报告三产物、Run 状态机、数据状态统一、前端只读工作台。

## 当前主链

固定生产主链：

```text
api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output
```

当前代码中的主触发路径：

1. `apps/api/main.py`
   - `POST /api/tasks/premarket`
   - `POST /tasks/premarket`
2. `apps/scheduler/runner.py`
   - `dispatch_premarket_task()`
3. `apps/worker/runner.py`
   - `run_premarket()`
4. `apps/worker/pipelines/macro.py`
   - macro collect / feature / report render
5. `apps/worker/pipelines/cme.py`
   - CME download / parse / ingest / option wall
6. `apps/analysis/*`
   - analysis snapshot、domain agents、coordinator、strategy card
7. `apps/renderer/*`、`apps/output/*`
   - Markdown / HTML / JSON artifact 输出

## 当前前端

正式前端入口：

```text
apps/frontend-web/src
```

技术栈：

- Vite
- React 18
- TypeScript
- React Router
- lucide-react
- Tailwind CSS

`apps/frontend-web/src/main.tsx` 定义当前页面路由。`apps/frontend/` 当前不作为主线入口；`/dashboard` 在 FastAPI 中只是跳转到 Vite `/dashboard`。

## 当前后端

技术栈：

- FastAPI
- SQLAlchemy 2.0 style models
- PostgreSQL / SQLite-compatible JSON fallback
- APScheduler background jobs
- uv Python environment

主要目录：

- `apps/api/`：FastAPI 路由、schemas、services
- `apps/scheduler/`：任务派发和定时刷新
- `apps/worker/`：premarket pipeline 执行
- `apps/collectors/`：FRED、Fed、Treasury、DXY、CME、Jin10 等采集
- `apps/parsers/`：CME、macro、Jin10 等解析
- `apps/features/`：宏观、期权等确定性特征
- `apps/analysis/`：分析快照、domain agents、策略卡片
- `apps/renderer/`：Markdown / HTML 渲染
- `apps/output/`：artifact 写入和外部输出工具
- `database/`：models、queries、migrations
- `storage/`：raw / parsed / features / outputs / logs

## 当前文档基线

本轮文档整理生成：

- 真实代码审计：`docs/audit/CURRENT_PROJECT_AUDIT.md`
- 架构文档：`docs/01_ARCHITECTURE.md`
- 后端主链：`docs/02_BACKEND_PIPELINE.md`
- 前端页面：`docs/03_FRONTEND_PAGES.md`
- 数据模型与存储：`docs/04_DATA_MODEL_AND_STORAGE.md`
- Agent / 报告 / 溯源：`docs/05_AGENT_ARCHITECTURE.md`、`docs/06_REPORT_SYSTEM.md`、`docs/07_SOURCE_TRACE_AND_RUN.md`
- Roadmap：`docs/08_BACKEND_ROADMAP.md`、`docs/09_FRONTEND_ROADMAP.md`
- 图：`docs/diagrams/*.mmd`
