# finance-agent

`finance-agent` 是一个本地可运行、可追溯、可复盘的金融研究中台，当前聚焦 XAUUSD / GC 黄金相关市场。系统用于采集官方与市场数据、解析和计算确定性特征、生成分析快照、产出报告与策略卡片，并通过 React 工作台展示只读分析、数据状态、任务运行和人工复核信息。

本项目不是自动交易系统，不包含自动下单能力。仓库内容仅用于研究、工程演示和本地复盘，不构成投资建议。

## 安全与合规声明

- 默认只建议在本机或受信任内网运行，不要把 FastAPI、Dashboard、任务触发接口或本地数据目录裸露到公网。
- 如需部署到共享环境或公网，必须自行增加认证、反向代理、IP allowlist、CORS 限制、任务触发权限控制和日志脱敏。
- 使用者需要自行遵守 FRED、Fed、Treasury、CME、Jin10、OpenBB、yfinance、Reuters metadata 等数据源的服务条款；本项目不附带任何数据再分发授权。
- 不要提交 `.env`、API key、token、cookie、私钥、证书、浏览器登录态、真实报告产物或本地运行数据。

## 当前主链

生产主链固定为：

```text
api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output
```

核心原则：

- 后端负责采集、解析、特征计算、分析、报告生成和结构化 read model。
- 前端只消费 API 和展示状态，不计算策略结论。
- LLM / Agent 不替代确定性计算；确定性指标先由 `collectors`、`parsers`、`features` 生成。
- 每个结论尽量绑定 `run_id`、`snapshot_id`、`source_refs`、`artifact_refs`。
- 缺失数据必须显式暴露为 `unavailable` / `fallback` / `mock` / `manual_required`，不伪装成实时数据。

## 技术栈

后端：

- Python 3.11
- FastAPI
- SQLAlchemy
- PostgreSQL / Redis
- APScheduler
- Dagster
- uv

前端：

- Vite
- React 18
- TypeScript
- React Router
- Tailwind CSS
- React Flow / Dagre

主要数据源和能力：

- FRED / Fed / Treasury 宏观流动性数据
- CME / COMEX Daily Bulletin 与期权结构
- Jin10 新闻、日历、快讯、行情和报告
- 市场行情、技术结构、仓位、市场 odds
- Agent 分析、报告三产物、策略卡片、SourceTrace

## 目录结构

```text
apps/
  api/              FastAPI app、schemas、services
  scheduler/        定时任务和任务派发
  worker/           premarket / news / macro / CME pipeline
  collectors/       外部数据采集
  parsers/          raw -> structured parser
  features/         deterministic feature builder
  analysis/         snapshots、domain agents、strategy card
  renderer/         Markdown / HTML renderer
  output/           artifact 写入和外部输出
  frontend-web/     Vite + React 正式前端
dagster_finance/    Dagster definitions、jobs、ops、schedules
database/           models、queries、migrations
docs/               架构、API、页面、数据和路线图文档
scripts/            本地启动、回填、发布、维护脚本
storage/            raw / parsed / features / outputs 占位目录
tests/              API、pipeline、collector、feature、renderer 测试
```

正式前端入口只使用 `apps/frontend-web/src`。旧 Next.js 前端和 FastAPI 直出 dashboard 不作为新功能入口。

## 快速启动

前置条件：

- Python 3.11
- Node.js 18+
- uv
- 本机 PostgreSQL / Redis，或本仓库脚本配置的 user-space PostgreSQL / Redis

首次初始化：

```bash
cp .env.example .env
uv sync --extra dev
cd apps/frontend-web
npm install
```

`.env` 只放本地真实配置，已被 `.gitignore` 排除。不要把真实 key、token、密码或 cookie 写入仓库。

启动本地栈：

```bash
export no_proxy=127.0.0.1,localhost,::1
./start.sh start
```

常用入口：

```text
API health:  http://127.0.0.1:8000/health
Frontend:    http://127.0.0.1:8080
Dashboard:   http://127.0.0.1:8080/dashboard
API docs:    http://127.0.0.1:8000/docs
```

本地栈管理：

```bash
./start.sh status
./start.sh logs
./start.sh restart
./start.sh stop
./start.sh stop --with-deps
```

默认 `./start.sh start` 会启动完整开发栈：

- user-space PostgreSQL / Redis
- FastAPI API（默认 `:8000`）
- Vite 前端 dev server（默认 `:8080`）

如需只构建前端静态产物并通过 FastAPI 兼容入口提供 `/dashboard`，使用：

```bash
./start.sh start --frontend=build
```

如需只启动后端，不管理前端：

```bash
./start.sh start --frontend=none
```

脚本支持 dry-run：

```bash
./start.sh start --dry-run
```

可选环境变量：

```bash
FINANCE_AGENT_API_PORT=8000
FINANCE_AGENT_FRONTEND_PORT=8080
FINANCE_AGENT_FRONTEND_MODE=dev
FINANCE_AGENT_EVENT_FLOW_TRANSLATION_PROVIDER=mimo
FINANCE_AGENT_EVENT_FLOW_TRANSLATION_MODEL=mimo-v2.5
```

如需让 Event Flow 页面在后端直接调用 `mimo` 把英文事件标题/摘要翻成中文，可这样启动：

```bash
FINANCE_AGENT_EVENT_FLOW_TRANSLATION_PROVIDER=mimo \
FINANCE_AGENT_EVENT_FLOW_TRANSLATION_MODEL=mimo-v2.5 \
./start.sh restart
```

## 关键命令

后端验证：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/uv-cache FINANCE_AGENT_DISABLE_BACKGROUND_JOBS=1 uv run --extra dev pytest -q
```

前端验证：

```bash
cd apps/frontend-web
npm run build
npm run typecheck
```

Dagster 本地开发：

```bash
uv run dagster dev -m dagster_finance.definitions
```

触发 premarket pipeline：

```bash
curl --noproxy '*' -X POST http://127.0.0.1:8000/api/tasks/premarket
```

查看任务：

```bash
curl --noproxy '*' http://127.0.0.1:8000/api/tasks
curl --noproxy '*' http://127.0.0.1:8000/api/runs
```

## 环境变量

以 `.env.example` 为模板：

```bash
cp .env.example .env
```

常用字段：

| 变量 | 用途 |
| --- | --- |
| `DATABASE_URL` | 后端数据库连接，默认本地 PostgreSQL 55432 |
| `REDIS_URL` | Redis 连接 |
| `FRED_API_KEY` | FRED 宏观数据 |
| `OPENAI_API_KEY` | LLM 分析能力 |
| `FEISHU_*` | 飞书通知或 Jin10 群消息采集 |

安全约束：

- `.env`、`.env.local`、key 文件、证书文件不提交。
- `storage/raw`、`storage/parsed`、`storage/features`、`storage/outputs` 只提交 `.gitkeep`，运行数据不提交。
- 本地 agent、编辑器缓存、索引目录和运行辅助目录不提交。

## API 与页面

核心 API：

- `GET /health`
- `POST /api/tasks/premarket`
- `GET /api/tasks`
- `GET /api/runs`
- `GET /api/dashboard/summary`
- `GET /api/data-sources/status`
- `GET /api/reports/index`
- `GET /api/strategy-cards/latest`
- `GET /api/events/flow/overview`
- `GET /api/source-trace/{snapshot_id}`

完整 API 映射见 [docs/10_API_MAP.md](docs/10_API_MAP.md)。

前端页面职责见 [docs/03_FRONTEND_PAGES.md](docs/03_FRONTEND_PAGES.md) 和 [docs/11_PAGE_RESPONSIBILITY_MATRIX.md](docs/11_PAGE_RESPONSIBILITY_MATRIX.md)。

## 文档入口

建议阅读顺序：

1. [AGENTS.md](AGENTS.md)：项目主约束、架构边界、命令约定、验收原则。
2. [docs/00_PROJECT_OVERVIEW.md](docs/00_PROJECT_OVERVIEW.md)：项目定位和当前状态。
3. [docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md)：总体架构。
4. [docs/02_BACKEND_PIPELINE.md](docs/02_BACKEND_PIPELINE.md)：后端主链。
5. [docs/04_DATA_MODEL_AND_STORAGE.md](docs/04_DATA_MODEL_AND_STORAGE.md)：数据模型和存储。
6. [docs/07_SOURCE_TRACE_AND_RUN.md](docs/07_SOURCE_TRACE_AND_RUN.md)：Run / Snapshot / SourceTrace。

文档总入口见 [docs/README.md](docs/README.md)。

## 提交前检查

提交前至少执行：

```bash
git status --short
git diff --check
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/uv-cache FINANCE_AGENT_DISABLE_BACKGROUND_JOBS=1 uv run --extra dev pytest -q
cd apps/frontend-web && npm run build
```

提交前还需要确认：

- 没有 `.env`、真实 key、token、cookie、私钥或证书。
- 没有运行数据、临时文档、agent skill、本地索引、构建产物。
- `.gitignore` 覆盖新增的本地生成目录。
- README 与 `docs/` 中的架构、命令和入口保持一致。
- 没有公开内部云文档 URL、Bitable token/table id、本地绝对路径、远程运维入口或浏览器登录态路径。
