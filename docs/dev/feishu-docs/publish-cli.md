# 飞书云文档发布命令

更新时间：2026-06-12

本文记录如何从 repo 发布到飞书 / Lark Docx 和 Bitable。正式发布前必须先 dry-run。

## 基本原则

- 常规模块更新优先使用 section publisher，不要全量清空重写。
- 不要把 token 或 secret 放到命令参数、脚本文件或 git diff。
- Mermaid / PlantUML 流程图必须走 Board / Whiteboard 小组件。
- 远端文档已有 ID 时优先更新现有文档，不要重复创建同名文档。

## 定向章节发布

只更新某个主题页或模块说明时使用：

```bash
rtk uv run python scripts/publish_feishu_section.py \
  --document-id Qijfd0pJsoQtjjxwJSycMthyn0b \
  --anchor news-data-pipeline \
  --doc-file docs/13_NEWS_DATA_PIPELINE.md \
  --diagram docs/diagrams/news-pipeline-flow.mmd \
  --dry-run
```

真实发布优先使用本地 OAuth：

```bash
rtk uv run python scripts/publish_feishu_section.py \
  --document-id Qijfd0pJsoQtjjxwJSycMthyn0b \
  --anchor news-data-pipeline \
  --doc-file docs/13_NEWS_DATA_PIPELINE.md \
  --diagram docs/diagrams/news-pipeline-flow.mmd \
  --auth-mode lark-cli
```

section publisher 会维护固定 marker：

```text
[[finance-agent-section:start:<anchor>]]
...正文、表格、Mermaid 画板...
[[finance-agent-section:end:<anchor>]]
```

第一次运行没有 marker 时会追加；后续运行只删除并重写该 marker 区间。

## 固定 baseline 全量发布

`scripts/publish_feishu_docs.py` 用于旧 baseline 三件套。默认 dry-run：

```bash
rtk uv run python scripts/publish_feishu_docs.py --dry-run
```

旧 baseline 包含：

- `finance-agent 项目现状审计`
- `finance-agent 架构与流程图`
- `finance-agent 改造规划`

真实覆盖旧文档必须显式确认：

```bash
rtk uv run python scripts/publish_feishu_docs.py --confirm-overwrite
```

只有明确要创建新一套远端文档时才使用：

```bash
rtk uv run python scripts/publish_feishu_docs.py --create-new
```

## 自定义 Docx 发布

```bash
rtk uv run python scripts/publish_feishu_docs.py \
  --preset custom \
  --title "finance-agent Mermaid 渲染测试" \
  --document-id <docx_document_id> \
  --doc-file docs/README.md \
  --diagram docs/diagrams/system-architecture.mmd \
  --confirm-overwrite
```

如果只是更新一个主题 section，优先改用 `scripts/publish_feishu_section.py`。

## 认证方式

只做 dry-run 不需要飞书凭证。

真实发布需要目标文件夹 token，并提供一种认证方式。

使用 access token：

```bash
export FEISHU_DOCS_FOLDER_TOKEN="<folder_token>"
export FEISHU_ACCESS_TOKEN="<access_token>"
rtk uv run python scripts/publish_feishu_docs.py --confirm-overwrite
```

使用应用凭证换取 tenant token：

```bash
export FEISHU_DOCS_FOLDER_TOKEN="<folder_token>"
export LARK_APP_ID="<app_id>"
export LARK_APP_SECRET="<app_secret>"
rtk uv run python scripts/publish_feishu_docs.py --confirm-overwrite
```

使用本地 OAuth：

```bash
lark-cli auth login --domain base,docs,drive
rtk uv run python scripts/publish_feishu_section.py \
  --document-id <docx_document_id> \
  --anchor <stable_anchor> \
  --doc-file <repo_doc.md> \
  --auth-mode lark-cli
```

如果真实写入返回 `Authentication token expired`，先重新授权，不要通过 `--create-new` 绕过。

## 发布后验收

至少检查：

- dry-run 的 `action` 是否符合预期。
- `markdown_files` / `diagrams` 是否只包含目标文件。
- `text_block_count`、`table_count`、`board_count` 是否合理。
- 真实发布后读回：目标 anchor start/end marker 各 1 个。
- Mermaid 不应在飞书显示为 Plain Text 代码块。

## 429 与频控

飞书 OpenAPI 返回 429 时，发布器会退避重试。新增发布器或 block builder 时仍需按官方 3 次/秒级限制做节流。
