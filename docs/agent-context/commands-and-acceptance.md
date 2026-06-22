# Commands And Acceptance

仅在需要运行项目命令、Mem0 预取、测试矩阵、smoke test、提交前验收或命令约定细节时读取。

## 命令约定

必须优先使用 `rtk` 执行外部命令以减少输出：

```bash
rtk git status --short
rtk git diff
rtk git log --oneline -10
rtk pytest -q
rtk npm run build
rtk vitest run
rtk tsc --noEmit
rtk lint
rtk ls -la
rtk tree -L 2
rtk find . -name "*.py" -type f
rtk grep -r "pattern" --include="*.py"
rtk json <file.json>
rtk err -- <command>
rtk diff <file1> <file2>
rtk summary -- <command>
```

Shell 内建命令、环境变量修改、会话状态使用原生 bash：

```bash
export PATH="$PATH:/home/zxx/.local/bin"
echo "$DATABASE_URL"
```

不要用 `rtk` 包装 shell 内建命令。

## Python / uv

- 项目 Python 依赖由 `uv` 管理，项目根固定 `.python-version = 3.11`，本地虚拟环境为 `.venv/`。
- 跑项目 Python 代码必须使用 `uv run python ...`，或明确使用 `.venv/bin/python`。
- 不要用裸 `python3 ...` 跑项目模块或脚本。

更新 Mem0 项目主线记忆时使用固定入口，不要临时写脚本：

```bash
uv run python scripts/mem0_add_project_memory.py --memory-type frontend_direction --content '...' --verify-query '...'
```

## Mem0 预取

在 `/home/zxx/workspace/finance-agent` 执行非平凡开发任务前，先读取 `AGENTS.md` 并预取项目记忆：

```bash
rtk uv run python scripts/mem0_prefetch_context.py "<task>"
```

跳过场景：普通问答、状态查询、简单 shell 命令、token/用量统计、纯格式化说明。

若命令提示任务未命中检索条件，则继续正常执行；若因 `MEM0_API_KEY` 缺失失败，报告失败并继续，不编造上下文。若上游上下文已注入 `## Mem0 Context`，执行 Agent 不需要重复查询 Mem0。

模型策略：普通开发任务默认使用 `gpt-5.4-mini`；复杂推理、架构判断或困难调试使用 `gpt-5.4`。

localhost smoke test 或长任务前保留小写：

```bash
export no_proxy=127.0.0.1,localhost,::1
```

## 验收矩阵

按改动范围选择验证：

- API：跑 API tests 和 `/health`。
- worker/pipeline：跑 smoke test。
- collector：保存 raw 样本并跑采集测试。
- parser：跑 fixture regression。
- features：跑公式和边界测试。
- renderer/output：检查 Markdown/JSON 非空和字段完整。
- dashboard：打开页面检查只读 API 是否可消费。
- 前端：跑 `rtk tsc --noEmit`、`rtk npm run build`，必要时补浏览器截图、console、network、DOM 或 API 证据。

完成前必须说明：

- 改了哪些文件。
- 跑了哪些验证。
- 哪些验证没跑，原因是什么。

执行 Agent 任务派发需以真实执行输出、diff、日志或测试结果为准；仅输入框文本或 tmux 注入不算完成。

## 输出控制

- 大 diff 限定文件或用 `rtk diff`。
- 日志默认只看尾部或错误摘要。
- JSON 优先提取字段，不整文件输出。
- 测试输出优先 `rtk summary -- ...` 或 `rtk err -- ...`。
