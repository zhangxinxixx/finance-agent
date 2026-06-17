# 飞书工程文档中台 V2

更新时间：2026-06-12

V2 是当前推荐的远端云文档结构：Docx 保持短、清晰、可读；Bitable 承载长表格和台账。

## 结构

```text
finance-agent 工程文档中台 V2
├── 使用入口 Docx
├── 架构流程图 Docx
└── 工程台账 Bitable
```

## 为什么使用 V2

旧 baseline 把大量 Markdown 和表格写入 Docx，阅读和维护成本高。V2 做了拆分：

- Docx：入口说明、短段落、Mermaid 小组件。
- Bitable：API 映射、页面职责矩阵、后端 / 前端改造规划、风险和模块状态。

## Manifest

当前远端 ID 记录在：

```text
docs/feishu_publish_manifest.v2.json
```

manifest 只保存文档 URL、doc/base/table ID 和记录数量，不保存 token 或 secret。

## Dry-run

```bash
rtk uv run python scripts/publish_feishu_workspace_v2.py --dry-run
```

## 创建 V2

只有明确要创建新一套 V2 时使用：

```bash
rtk uv run python scripts/publish_feishu_workspace_v2.py --create-new
```

## 更新现有 V2

继续补全现有 V2，不要新建一套时使用：

```bash
rtk uv run python scripts/publish_feishu_workspace_v2.py --dry-run --update-existing
rtk uv run python scripts/publish_feishu_workspace_v2.py --update-existing --auth-mode lark-cli
```

`--update-existing` 会读取 `docs/feishu_publish_manifest.v2.json`，并只向现有 `finance-agent 工程台账 V2` 追加 manifest 中缺失的表。已经存在的表会跳过，避免重复写入记录。

## 当前 Bitable 表

| 表名 | 用途 |
| --- | --- |
| `API_MAP` | API 与页面 / 用途映射。 |
| `PAGE_MATRIX` | 页面职责矩阵。 |
| `ROADMAP` | 后端 / 前端改造规划。 |
| `RISKS_TODO` | 风险与待办。 |
| `DATA_MODEL_STORAGE` | 数据模型与 storage 分层。 |
| `MODULE_STATUS` | 审计中的模块 / API / 页面 / 模型状态。 |

## 阅读方式

- 先打开“使用入口”文档。
- 看流程图时打开“架构流程图”文档，图是 Mermaid 小组件。
- 查 API、页面职责和路线图时打开“工程台账 V2”多维表格，用飞书视图筛选和排序。

## 后续优化

- Bitable 记录写入改成 batch create，减少 OpenAPI 调用次数。
- 给 `ROADMAP` 增加优先级、负责人、计划状态、验收状态字段。
- 给 `API_MAP` 增加页面筛选视图、Mock / Live 状态字段。
- 给 `PAGE_MATRIX` 增加当前证据路径和下一步动作字段。
