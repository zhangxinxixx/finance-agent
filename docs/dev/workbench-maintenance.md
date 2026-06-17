# tmux 多 Agent 工作台维护指南

## 目的

这份指南只维护一件事：让 Hermes + 可视化 `codex exec` job + 前后端 Codex 交互窗口长期可用、可恢复、可交接。当前固定布局为单窗口三分屏。

## 单一入口

- 启动工作台：`dev-finance`
- 派发现有前端 pane：`scripts/dev-dispatch.sh frontend <task-file>`
- 派发现有后端 pane：`scripts/dev-dispatch.sh backend <task-file>`
- 派发 review：`scripts/dispatch-visible.sh review <task-file>`
- 强制开 job 窗口：`DEV_DISPATCH_FORCE_JOB=1 scripts/dev-dispatch.sh <frontend|backend> <task-file>`

## 最短操作

- 三个 pane 名字固定为：`0-hermes`、`1-frontend-tui`、`2-backend-tui`
- 它们都在同一个 tmux 窗口：`dev-board`
- Hermes 给前端派发：`scripts/dev-dispatch.sh frontend hermes/prompts/<task>.md`
- Hermes 给后端派发：`scripts/dev-dispatch.sh backend hermes/prompts/<task>.md`
- `scripts/dev-dispatch.sh` 默认优先发送到现有 Codex pane，不新开窗口
- 只有现有 pane 不可用时，才会自动回退到 `scripts/dispatch-visible.sh`
- 如果你明确要新开 job 窗口：`DEV_DISPATCH_FORCE_JOB=1 scripts/dev-dispatch.sh frontend hermes/prompts/<task>.md`

## 当前约定

- Hermes 是总控，只负责目标、边界、优先级、验收。
- 前端 Codex 只处理 `apps/frontend-web`。
- 后端 Codex 只处理后端主链相关内容。
- review 任务默认只读执行。
- 前后端任务不要互相直连；Hermes 默认通过 `scripts/dev-dispatch.sh` 发送到现有 Codex pane。
- 默认模型按本机策略走 Sub2API：普通开发任务优先 `gpt-5.4-mini`，复杂推理再升 `gpt-5.4`。

## 飞书远程入口

本机已通过 `lark-channel-bridge` 绑定飞书机器人 `分析助手`，用于从飞书聊天窗口远程调用本机 Codex CLI。

当前固定 profile：

- Bridge profile：`codex`
- Agent：`codex`
- Workspace：`/home/zxx/workspace/finance-agent`
- App ID：`cli_a96897c5f979dbd3`
- 本地配置：`~/.lark-channel/config.json`

常用命令：

```bash
lark-channel-bridge ps
lark-channel-bridge profile list
lark-channel-bridge status --profile codex
lark-channel-bridge start --profile codex
lark-channel-bridge stop --profile codex
lark-channel-bridge restart --profile codex
```

前台调试时使用：

```bash
no_proxy=127.0.0.1,localhost,::1 lark-channel-bridge run --profile codex
```

后台常驻时使用：

```bash
lark-channel-bridge start --profile codex
```

飞书消息写法建议：

- 明确目标、允许修改范围、禁止修改范围和验收命令。
- 开发任务仍需遵守 `AGENTS.md`：先读规则，必要时跑 Mem0 prefetch，最小改动，真实验证。
- 飞书消息被 bridge 接收不等于任务已完成；验收仍以 Codex 输出、diff、日志、测试结果或 `lark-channel-bridge ps/status` 为准。
- 如果后台不可用，先看 `lark-channel-bridge ps` 和 `lark-channel-bridge status --profile codex`，再改用前台 `run` 查看实时错误。

## Playwright MCP 浏览器入口

项目已接入 Playwright MCP，作为网页登录态取证和本地前端验收工具。它只用于浏览器操作、页面读取、截图、console/network 证据收集，不替代生产 worker 主链。

配置入口：

- Codex 项目配置：`.codex/config.toml`
- 启动脚本：`scripts/start_playwright_mcp.sh`
- 使用说明：`docs/dev/playwright-mcp.md`

常用检查：

```bash
codex mcp list
npx --yes @playwright/mcp@latest --help
bash -n scripts/start_playwright_mcp.sh
```

HTTP 联调入口：

```bash
scripts/start_playwright_mcp.sh http-local
```

金十 VIP 登录态调试入口：

```bash
JIN10_BROWSER_PROFILE=/home/zxx/.hermes/jin10_browser_profile \
  scripts/start_playwright_mcp.sh http-jin10
```

注意：同一个浏览器 `user-data-dir` 不要被多个进程同时写入；抓取结果必须先落 raw/parsed 证据，不能直接进入分析层。

## 维护原则

1. 只保留一个工作台脚本事实源
   - `scripts/dev-tmux.sh`：创建和展示单窗口三分屏工作台
   - `scripts/send-to-codex-pane.sh`：安全发送到现有 Codex pane
   - `scripts/dev-dispatch.sh`：优先走现有 pane，失败再回退到 job window
   - `scripts/dispatch-visible.sh`：给指定角色新开可视化 job window
   - `scripts/codex-live.sh`：在前台运行 `codex exec --json` 并记录日志

2. 只保留一份当前任务入口
   - `docs/dev/current-task.md`

3. 改动要可恢复
   - 优先改脚本和文档，不直接散落到多个地方
   - 每次改动后先 `bash -n` 再看 `git status`

4. 维持布局命名稳定
   - 窗口：`dev-board`
   - pane：`0-hermes`
   - pane：`1-frontend-tui`
   - pane：`2-backend-tui`

额外窗口按需出现：
- `job-<role>-<time>`：`scripts/dispatch-visible.sh` 动态新开
- `review`、`logs-live`、`services`：稳定后再决定是否加回固定窗口

5. 维护时优先检查这三件事
   - tmux `dev-board` 和 3 个 pane 是否还在
   - `codex --profile frontend/backend/review --help` 是否正常
   - `~/.codex/config.toml` 是否仍然保留 Sub2API 路由和 profile

6. 正常协作优先前台可视化
   - Hermes 到前端/后端的主流程用 `scripts/dev-dispatch.sh`
   - `scripts/dev-dispatch.sh` 会先检查目标 pane 当前是不是 Codex；只有安全时才发送
   - 现有 pane 不可用时，再回退到 `scripts/dispatch-visible.sh`
   - 注意：dispatcher 输出 `sent to <role> pane` 只证明任务文本送达，不等于 Codex 已经执行完。验收时必须继续用 `tmux capture-pane`、日志或 Codex 输出标记确认模型实际回写。
   - 交互式 Codex 窗口保留给人工会话，启动命令改为 `codex --no-alt-screen --profile frontend|backend|review`
   - `scripts/codex-live.sh` 会把任务文件复制到日志目录，并把 stdout/stderr 同时 tee 到 `all.log` 和 `events.jsonl`
   - `scripts/watch-agent-logs.sh` 负责在 `5-logs-live` 窗口动态跟踪新增日志文件

## 排障顺序

1. `tmux list-windows -t finance-dev -F '#I:#W'`
2. `bash -n scripts/codex-live.sh scripts/dispatch-visible.sh scripts/dev-dispatch.sh scripts/dev-tmux.sh scripts/watch-agent-logs.sh`
3. `scripts/dev-dispatch.sh frontend <task-file>`
4. `scripts/dev-dispatch.sh backend <task-file>`
5. `codex --no-alt-screen --profile frontend`
6. `codex --no-alt-screen --profile backend`
7. `git status --short`

## 常见问题

### 1. 中文任务被 shell 当命令执行了

说明目标 pane 不是 Codex，或者根本没走安全派发。直接改用：

```bash
scripts/dev-dispatch.sh frontend hermes/prompts/你的任务.md
```

### 2. 没有自动新开 job 窗口

先看 tmux session 是否存在：

```bash
tmux has-session -t finance-dev
```

如果不存在，先运行 `dev-finance`。如果存在，再执行：

```bash
scripts/dev-dispatch.sh frontend hermes/prompts/你的任务.md
```

如果你就是想强制开新 job 窗口：

```bash
DEV_DISPATCH_FORCE_JOB=1 scripts/dev-dispatch.sh frontend hermes/prompts/你的任务.md
```

### 3. 现在为什么没有固定 logs-live 窗口

当前设计就是先不开固定日志窗口。需要看日志时手动执行：

```bash
./scripts/watch-agent-logs.sh
```

或先确认日志根目录：

```bash
find /home/zxx/workspace/finance-agent-workbench/logs/agents -maxdepth 2 -type f | sort
```

### 4. frontend/backend profile 又变回非预期模型

检查 `~/.codex/config.toml`：

- `[profiles.frontend]`
- `[profiles.backend]`
- `[profiles.review]`

确认它们仍然通过本地 Sub2API 路由，并符合当前模型策略。

### 5. 新增任务模板

如果以后要加更细的交接流程，优先新增：

- `docs/dev/handoff-frontend.md`
- `docs/dev/handoff-backend.md`

不要把临时任务说明散落到聊天记录里。

## 变更建议

如果要改工作台，优先改这几个文件：

- `scripts/dev-tmux.sh`
- `scripts/send-to-codex-pane.sh`
- `scripts/dev-dispatch.sh`
- `scripts/dispatch-visible.sh`
- `scripts/codex-live.sh`
- `scripts/watch-agent-logs.sh`
- `docs/dev/current-task.md`
- `docs/dev/workbench-maintenance.md`

## 结论

这个工作台的维护核心是：

- 一个启动入口
- 一个派发入口
- 一个当前任务入口
- 一个维护说明入口

当前主派发入口是 `scripts/dev-dispatch.sh frontend|backend <task-file>`。它不是手写 `tmux send-keys`，而是通过 `scripts/send-to-codex-pane.sh` 安全定位现有 Codex pane、检查进程、清空输入、paste 并提交；只有现有 pane 不可用时才 fallback 到 `scripts/dispatch-visible.sh` 新开 job 窗口。
