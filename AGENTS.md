# finance-agent / AGENTS.md

本文件给开源协作者和自动化 coding agent 提供仓库内的高频约束。真实密钥、本地登录态、运行数据和私有运维入口不得写入仓库。

## 默认执行风格

- 默认使用简体中文交流，除非任务明确要求其他语言。
- 保留命令、代码、路径、环境变量、接口字段名的原文。
- 优先给结论、修改点、关键代码和验证结果；不确定时明确说明，不编造文件、变量、接口或依赖。
- 改动保持小而直接；先验证当前链路，再扩大范围。

## 项目定位与主链

这是一个本地可运行、可追溯、可复盘的金融研究中台，不是自动交易系统，不包含自动下单能力，也不构成投资建议。

生产主链固定为：

```text
api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output
```

新增能力应挂到这条主链路中，不要新增第二套任务主脑。

## 架构与数据边界

可以做：

- 补 `collectors`、`parsers`、`features`、`analysis`、`renderer`。
- 补 `api` 只读接口。
- 补 `apps/frontend-web/src` 下的只读页面和组件。
- 补测试、迁移、脚本、文档。

禁止做：

- 不要让前端自己计算策略结论。
- 不要让 Agent 直接改原始数据。
- 不要绕过 `task_runs` 和 `task_steps`。
- 不要覆盖历史报告。
- 不要为了重构破坏当前可运行链路。

数据原则：

- `raw`、`parsed`、`features`、`outputs` 分层不能混。
- 原始 API 响应和 PDF 文件必须归档到本地运行目录，但不要提交真实运行数据。
- AI 分析结果应绑定 `input_snapshot_ids` 和 `source_refs`。
- 缺失数据必须显式标记，不允许补造。

## 前端入口规则

- 正式前端只使用 `apps/frontend-web/src`。
- `apps/frontend/` 旧入口和早期直出 HTML 不作为新功能入口。
- FastAPI `/dashboard` 仅作为兼容跳转，真实页面以 Vite `/dashboard` 为准。

## 代码修改与检索原则

- 修改代码前先说明影响范围和验证方式。
- 单文件小改只读当前文件和必要邻近上下文。
- 跨文件开发、数据链路、报告产物、前端验收或发布前清理，需要先写简短 Plan/Spec。
- 优先使用 `rg` 或 `git grep` 精准定位；检索默认排除 `node_modules`、`.git`、`dist`、`build`、`.venv`、缓存和生成物目录。
- routes 保持轻逻辑，业务逻辑放到 services/repositories。
- parser 改动必须补样本或回归测试。
- 输入一律视为不可信；涉及路径、命令、外部参数、上传内容时优先使用白名单和结构化 API。

## 命令与验证

项目 Python 依赖由 `uv` 管理，项目根固定 `.python-version = 3.11`。

- 跑项目 Python 代码使用：`uv run python ...`，或明确使用 `.venv/bin/python`。
- 本地 smoke test 或长任务前建议设置：`no_proxy=127.0.0.1,localhost,::1`。

按改动范围选择验证：

- API：跑相关 API tests，并检查 `/health`。
- worker/pipeline：跑 smoke test。
- collector：保存 raw 样本并跑采集测试。
- parser：跑 fixture regression。
- features：跑公式和边界测试。
- renderer/output：检查 Markdown/JSON 非空和字段完整。
- dashboard：确认页面可消费只读 API。

完成前必须说明：

- 改了哪些文件。
- 跑了哪些验证。
- 哪些验证没跑，原因是什么。

## 公开仓库安全规则

- 不提交 `.env`、真实 key、token、cookie、私钥、证书、浏览器 profile、运行数据或本地报告产物。
- 不提交内部云文档 URL、Bitable app token、table id、远程运维入口、个人本地路径或私有协作协议。
- 如果历史里曾经提交过真实 secret，必须先轮换 secret，并在公开前清理 Git 历史。
