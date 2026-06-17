# Playwright MCP 接入说明

## 定位

Playwright MCP 是项目的浏览器取证和页面验收工具，不是生产 worker 主链，也不是新的数据采集主脑。

适用范围：

- 使用真实浏览器登录态读取金十 VIP、TradingView 或内部后台页面。
- 对本地 Vite 前端做可访问性快照、点击、表单、console、network、截图验收。
- 保存网页原文、表格、图表位置、截图或 HTML 证据，供后续 parser / renderer 消费。

不适用范围：

- 不自动化交易。
- 不绕过站点权限、付费墙或风控。
- 不把网页抓取结果直接送进分析层；必须先落 raw，再进入 parsed / features / analysis。
- 不在前端计算策略或改写 artifact。

## Codex 项目配置

项目级 MCP 配置位于 `.codex/config.toml`：

```toml
[mcp_servers.playwright]
command = "/home/zxx/workspace/finance-agent/scripts/start_playwright_mcp.sh"
args = ["stdio-local"]
```

默认 profile：

```text
~/.hermes/playwright_mcp_profile/finance-agent
```

默认输出：

```text
output/playwright-mcp/local/
```

`output/playwright-mcp/` 是本地运行证据目录，不应提交。

## 抓取替换方案

Playwright MCP 可以替换之前不稳定的网页登录态抓取动作，但只先替换浏览器取证层。正式 parser、analysis、renderer 和 scheduler / worker 主链不直接替换。

详细执行方案见：

```text
docs/superpowers/plans/2026-06-08-playwright-mcp-fetch-replacement.md
```

当前决策：

- MCP 先用于打开登录态页面、点击、滚动、等待动态内容、保存 HTML / 截图 / 图表位置。
- 抓取结果必须先落 `storage/raw/browser/...`，清洗后再进入 `storage/parsed/browser/...`。
- 稳定后的选择器和交互步骤再固化回 `scripts/fetch_jin10_report.py` 或 collector 代码。
- 不让 MCP 直接生成市场分析，不让 MCP 直接写最终报告。

## 启动方式

Codex 内使用 stdio MCP 时无需手工启动，配置会调用：

```bash
scripts/start_playwright_mcp.sh stdio-local
```

需要给其他 MCP client 或手工联调时，启动 HTTP server：

```bash
scripts/start_playwright_mcp.sh http-local
```

默认监听：

```text
http://127.0.0.1:8931
```

金十 VIP 已有浏览器登录态时使用：

```bash
JIN10_BROWSER_PROFILE=/home/zxx/.hermes/jin10_browser_profile \
  scripts/start_playwright_mcp.sh http-jin10
```

或者在 Codex / MCP stdio 场景改用：

```bash
scripts/start_playwright_mcp.sh stdio-jin10
```

注意：同一个 `user-data-dir` 不要被多个 Chrome / Playwright 进程同时写入。

## 典型任务提示

只抓取金十 VIP 原文：

```text
打开金十 VIP 报告页面，读取今天最新黄金报告标题、正文、图表说明和图表位置。
只保存原文、HTML、截图和图表位置，不做市场分析。
输出 raw/parsed 边界建议和证据路径。
```

验收本地前端：

```text
打开 http://localhost:5173/reports，检查页面是否有布局错位、按钮不可点击、console error、接口报错。
给出具体 DOM / network / screenshot 证据和修复建议。
不要改业务逻辑，除非我明确要求修复。
```

## 数据落盘边界

网页登录态抓取结果按项目数据分层处理：

- 原始 HTML、截图、页面快照：`storage/raw/browser/<source>/<date>/...`
- 清洗后的正文、表格、图表索引：`storage/parsed/browser/<source>/<date>/...`
- 分析报告、策略卡片：只能由既有 analysis / renderer 链路生成。

若只是一次性验收，截图和 MCP session 可留在：

```text
output/playwright-mcp/
```

## 安全约束

- 不提交 cookies、storage state、`.env`、截图中的敏感信息。
- MCP 的 `--allowed-origins` / `--blocked-origins` 不是安全边界；敏感站点抓取仍需人工确认目标 URL。
- 默认阻断云 metadata 地址：
  - `http://169.254.169.254`
  - `http://metadata.google.internal`
- 不启用 `--allow-unrestricted-file-access`。
- 金十 / TradingView 抓取必须保留来源 URL、抓取时间、登录态 profile 名称和失败原因。

## 验证命令

```bash
codex mcp list
npx --yes @playwright/mcp@latest --help
bash -n scripts/start_playwright_mcp.sh
timeout 8s scripts/start_playwright_mcp.sh http-local
```

`timeout` 结束码为 `124` 表示 server 成功保持运行后被测试命令主动停止。
