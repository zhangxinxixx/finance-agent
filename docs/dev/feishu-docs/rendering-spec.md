# 飞书 Docx 渲染规范

更新时间：2026-06-12

本文是后续通用 Feishu/Lark Docx renderer 的设计规范。它不绑定新闻链；新闻链、日报、任务计划、项目状态都应作为通用 renderer 上的模板。

## 目标

不要把原始 Markdown 逐段写进飞书，而是先构造飞书专用阅读版面，再映射到 Docx Block、表格、画板和媒体。

推荐链路：

```text
structured input
-> FeishuDocModel
-> layout components
-> Docx block plan
-> anchored section publisher
-> read-back validation
```

## 设计原则

1. 首屏必须是结论、状态和入口，细节后置。
2. 结论、风险、注意事项用 Callout / 高亮块。
3. 状态、P0/P1/P2、数据源清单用短表、状态卡或分栏。
4. 长台账放 Bitable，不塞进 Docx 长表。
5. Mermaid / PlantUML 一律发布为画板，不写 fenced code block。
6. 命令、JSON、SQL 才用代码块；普通说明不用代码块。
7. 发布器必须支持 dry-run、节流、429 退避和读回验收。
8. 每个可重复更新的主题使用稳定 anchor，避免整篇覆盖。

## 核心抽象

通用抽象应保持领域无关：

```python
FeishuDoc:
  title: str
  sections: list[Section]
  summary: list[MetricCard]
  callouts: list[Callout]
  tables: list[Table]
  diagrams: list[Diagram]
  source_links: list[Link]
```

推荐对象：

- `Section`
- `Callout`
- `MetricCard`
- `Table`
- `Diagram`
- `TaskList`
- `SourceLink`

不推荐把 `NewsPipelineDoc` 这类领域对象做成核心抽象。领域模板可以存在，但必须建在通用组件之上。

## 建议模块

```text
scripts/
  publish_feishu_section.py        # 已有：按 anchor 定向发布
  feishu_doc_blocks.py             # 新增：低层 block builder
  feishu_doc_model.py              # 新增：通用文档意图模型
  feishu_doc_layouts.py            # 新增：高层 layout/component builder
```

测试放在：

```text
tests/scripts/test_feishu_doc_blocks.py
tests/scripts/test_feishu_doc_model.py
tests/scripts/test_feishu_doc_layouts.py
```

测试只断言 JSON shape 和本地 block plan，不依赖真实飞书。

## 最小 block builder 范围

第一版支持：

- text
- heading
- rich text elements
- bullet / ordered list
- quote
- code
- divider
- callout
- table
- board

可以复用现有 `scripts/publish_feishu_docs.py` 中的 `build_text_block`、`build_table_block`、`build_board_block`，再补 `build_callout_block`、`build_divider_block`、`build_rich_text_elements`。

## 布局组件

第一版支持：

- `title_header()`：标题、更新时间、状态。
- `summary_callout()`：一句话结论。
- `status_cards()`：状态卡或短表。
- `matrix_table()`：小型矩阵表。
- `risk_callouts()`：风险与边界。
- `task_phase_table()`：P0/P1/P2 任务表。
- `source_references()`：来源与链接区。

## 读回验收

真实发布后至少检查：

- anchor start/end marker 各 1 个。
- 目标标题存在。
- `board_count` 符合预期。
- 至少有一个 native 结构，例如 callout、table、divider 或 board。
- 不包含 Mermaid 源码文本。
- 没有把长 Markdown 表格直接灌进 Docx。

## 暂不做

- 暂不做 WYSIWYG 编辑器。
- 暂不把全部仓库 Markdown 自动转换为飞书文档。
- 暂不把飞书文档作为系统事实源。
- 暂不做复杂权限系统。
