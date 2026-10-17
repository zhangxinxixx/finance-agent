# 黄金宏观日报候选交付

`apps.worker.pipelines.gold_macro_daily` 复用现有输入校验、coordinator、research_synthesis、17项review、renderer和不可变writer。没有新采集器、Prompt、Agent、数仓或调度器。

- `prepare_gold_macro_daily(snapshot, source_root=...)` 只读取已有归档，保留事件和前序缺口；返回校验快照、完整模型输入和消息、字符数与指纹，不调用模型。
- 可显式传入 `archive_refs=[{kind, path, sha256, raw_root?}]`：`macro_release_events` 读取已有 MacroSnapshot 的 `release_events`，`official_events` 读取 `official_event_snapshot.v1`，`fedwatch` 读取现有采集器合同（也兼容已归档的 `job=fedwatch/result` 包装）。不从标题或FRED指数推造发布事实，不自动扫描、采集或挑选“最新”文件。先核对路径和指纹，再复用原发布/预期/接收时间、原生事件与FedWatch时效校验；缺预期保留实际值，缺同窗反应不补因果。
- 显式提供只读 `db_session` 时，通过已有报告注册查询和资格校验加载日报/周报全文；`no_autoflush` 防止读取触发隐式写入。`prior_report_root` 可与行情 `source_root` 分开，二者都是调用者指定的存储边界。不把文件存在、候选审阅通过或过期背景提升为合格前序；无session或库不可读时保留具体缺口。
- 全文加入后超过既有输入预算，返回 `blocked/research_input_budget_exceeded`、`model_calls=0`、`truncation=false`；不通过截断前序或反证来伪造完整输入。
- `generate_gold_macro_daily(prepared, source_root=..., storage_root=..., gateway=...)` 必须传入已授权且有调用预算的gateway；不使用默认模型。调用前重新核验归档和冻结消息。通过正常协调器绑定 `input_validation`，禁止临时替换协调器而漏传绑定。最多主生成一次、自动审阅一次，关闭格式修复和审阅后自动修订；带备用提供商的gateway配置会被拒绝。已有输出目录会在模型调用前拒绝重复生成。任务/步骤记录、调用预算及审计仍由现有worker调用方负责。
- 若准备时指定了 `prior_report_root`，生成时必须指定同一个目录。生成仅重验冻结归档与正文，不重新查询当下注册库改变历史；归档指纹、前序文件或存储边界变化均在模型前拒绝。归档接线不代表该归档具备当前时效，也不代替官方发布原件的生产端解析。
- 生成成功与审阅通过后，`complete_gold_macro_daily` 写入独立 `outputs/gold_macro_daily/XAUUSD/<date>/<run>/`，内含正文、审计附录、结构化记录。失败保留coordinator草稿供调用方审计，不写合格报告。不能把旧模型结果绑定新快照。
- `register_gold_macro_daily_bundle(db, directory=..., storage_root=...)` 验证完整Bundle后登记为 `gold_macro_daily_markdown`；不要求CME或策略卡片。函数不创建数据库连接、不提交事务，调用者选择目标session。相同Bundle重复登记不推进注册版本时间。
- 现有 `/api/reports/index`、`/{report_id}`、`/analysis`、`/evidence` 读取同一对象，核验三份产物及注册指纹；不以文件系统最新文件替换对象。无单独AnalysisSnapshot行时，从已核验Bundle中的绑定输入读取研究截止。读取端 `report_identity.model_review_status` 是模型自动审阅结果；`review_status=pending` 是正式发布待审，二者不混用。
- 现有React报告中心支持 `gold_macro_daily`、同日不同运行和候选资格；宏观日报不显示无关策略卡或日结基线卡。正文保留时间及不可发布提示。`gold_macro_daily.rendering.v1.2` 先呈现市场结论，再在时间精确匹配的金美元表格中标注“4小时端点窗口”、表下注释15分钟端点来源；原生PA的4H不改名。原模型响应和结构化模型正文不变，展示副本变换由renderer执行。自动审阅状态只表述一次，并保留独立质量基准未验收。

## 已记录响应的离线回放

`scripts/replay_gold_macro_daily.py` 用原prepared和两份实际请求/响应/审计记录走正常生成、审阅、保存及注册入口。它不请求模型；每次替换响应前严格比较完整消息。审计钩子拒绝网络连接、外部进程，模型客户端另行禁用。只写显式输出目录内的SQLite、TaskRun/TaskStep和Bundle；不连接生产数据库。

```bash
PYTHONDONTWRITEBYTECODE=1 no_proxy=127.0.0.1,localhost,::1 uv run python scripts/replay_gold_macro_daily.py \
  --prepared /path/to/prepared.json \
  --recorded-calls /path/to/calls \
  --source-root /path/to/frozen-source-root \
  --prior-report-root /path/to/frozen-prior-root \
  --output-root /path/to/new-workbench-output
```

`calls`必须包含 `01/02-http-request.json`、`01/02-full-response.txt`、`01/02-gateway-audit.json`。输出不能覆盖输入或无关的非空目录。同一目录重跑只复用已核验的同身份Bundle，不再回放响应，不推进报告注册版本。失败保留本地失败任务记录；不得自动开始新模型研究。

本入口只交付研究候选。`publish_allowed=false`、`execution_ready=false`、`research_quality=not_evaluated` 固定保留，不修改现有发布或交易资格门。候选正文可读不代表有资格作为生产前序报告；前序加载器继续执行原发布、注册版本与时间资格要求。

断网SQLite集成测试使用明确标识的合成模型响应，覆盖原生生成—审阅—Bundle—注册—API，不能当作实际模型能力验收。既有真实响应离线回放也不是新模型实验。生产session与工作日12:00调度仍需各自环境验收；隔离API和现有网页验收不代表已部署或真实定时运行，本入口不激活调度。
