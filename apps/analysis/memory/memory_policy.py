"""Mem0 记忆策略 —— 定义什么该进 Mem0，什么不该进。

原则：
  Mem0 只存项目主线摘要和执行约束。
  Obsidian 存完整文档。
  Git 存代码变更。
  Postgres / ClickHouse 存业务数据。
  MinIO / storage 存原始数据。

此模块提供校验函数，确保不会误将大段代码/文档写入 Mem0。
"""

from __future__ import annotations

# ── 允许存入 Mem0 的记忆类型 ──────────────────────────
ALLOWED_MEMORY_TYPES: frozenset[str] = frozenset(
    {
        "project_vision",
        "project_principle",
        "current_phase",
        "current_priority",
        "architecture_decision",
        "frontend_direction",
        "backend_direction",
        "agent_rule",
        "blocker",
        "next_action",
        "error_pattern",
        "user_feedback",
    }
)

# ── 不允许存入 Mem0 的内容模式 ─────────────────────────
FORBIDDEN_CONTENT_PATTERNS: list[tuple[str, str]] = [
    ("代码块", "```"),
    ("完整文件路径列表", r"^\s*(/[\w/]+)+\s*$"),
    ("SQL 语句", r"(?i)(SELECT\s|INSERT\s|UPDATE\s|DELETE\s|CREATE TABLE|ALTER TABLE)"),
    ("JSON 大段配置", r'(?i)^\s*[\[{]\s*"'),
]

# ── 内容长度限制 ──────────────────────────────────────
MAX_CONTENT_LENGTH: int = 2000  # 单条记忆内容上限（字符数）


class MemoryPolicy:
    """Mem0 记忆策略校验器。

    在写入 Mem0 前校验内容是否符合项目主线记忆规范。
    """

    @staticmethod
    def is_valid_memory_type(memory_type: str) -> bool:
        """检查记忆类型是否属于项目主线允许类型。"""
        return memory_type in ALLOWED_MEMORY_TYPES

    @staticmethod
    def is_content_valid(content: str) -> tuple[bool, str | None]:
        """校验内容是否符合 Mem0 存储规范。

        Returns:
            (是否通过, 失败原因)。通过时 reason 为 None。
        """
        if not content or not content.strip():
            return False, "内容为空"

        if len(content) > MAX_CONTENT_LENGTH:
            return False, (
                f"内容过长 ({len(content)} 字符)，超过上限 {MAX_CONTENT_LENGTH} 字符。"
                " 请精简为摘要格式。"
            )

        for pattern_name, pattern in FORBIDDEN_CONTENT_PATTERNS:
            import re

            if re.search(pattern, content):
                return False, f"内容疑似包含 {pattern_name}，不应存入 Mem0。"

        return True, None

    @staticmethod
    def sanitize_metadata(metadata: dict | None) -> dict:
        """清理 metadata，去除不应存入 Mem0 的字段。"""
        if metadata is None:
            return {}
        # 白名单字段
        allowed_keys = {
            "scope",
            "project_id",
            "memory_type",
            "tags",
            "importance",
            "source",
        }
        return {k: v for k, v in metadata.items() if k in allowed_keys}

    @staticmethod
    def validate_record(
        memory_type: str, content: str, metadata: dict | None = None
    ) -> tuple[bool, str | None]:
        """综合校验一条记忆记录。

        Returns:
            (是否通过, 失败原因)
        """
        if not MemoryPolicy.is_valid_memory_type(memory_type):
            return False, f"不允许的记忆类型: {memory_type}"

        ok, reason = MemoryPolicy.is_content_valid(content)
        if not ok:
            return False, reason

        return True, None


# ── 自动触发策略 ──────────────────────────────────────
# 独立函数（非 MemoryPolicy 静态方法），因为它们不依赖实例状态，
# 可直接被 Hermes/Codex 的会话 hook 调用，无需实例化 MemoryPolicy。


def should_retrieve(
    message: str,
    *,
    app_id: str | None = None,
    agent_id: str | None = None,
) -> bool:
    """判断当前消息是否应触发 Mem0 检索。

    检索条件（OR 关系）：
      1. 显式指定了 app_id 或 agent_id → 总是检索
      2. 消息命中项目关键词 → 检索
      3. 消息命中 Agent/架构/约束类关键词 → 检索

    不检索的场景：纯翻译、闲聊、临时问答等。
    """
    # 显式有上下文 → 总是检索
    if app_id or agent_id:
        return True

    msg_lower = message.lower()

    # 项目关键词
    project_keywords = [
        "金融分析系统", "finance.agent", "finance_agent",
        "宏观", "cme", "期权", "option", "持仓",
        "risk", "风险", "news", "新闻", "快讯", "技术面",
        "data pipeline", "数据管道", "collector", "parser",
    ]
    if any(kw.lower() in msg_lower for kw in project_keywords):
        return True

    # Agent / 架构 / 约束类关键词
    meta_keywords = [
        "agent", "rule", "规则", "架构", "architecture",
        "决策", "decision", "约束", "constraint",
        "memory", "mem0", "记忆", "obsidian",
        "codex", "hermes", "项目", "project",
        "阶段", "phase", "计划", "plan",
        "上次", "之前", "前面说", "我们以前", "上次说",
    ]
    return any(kw.lower() in msg_lower for kw in meta_keywords)


# ── 写入触发信号词 ────────────────────────────────────
_WRITE_SIGNALS = [
    "后续默认", "以后默认", "写入mem", "写入 mem",
    "写入mem0", "作为规则", "作为约束", "架构决策",
    "长期记忆", "记下来", "记住", "保存到记忆",
    "作为规范", "作为标准", "以后都", "今后都",
]


def should_write(message: str) -> bool:
    """判断当前消息是否应触发 Mem0 写入。

    写入是半自动的：必须用户消息中包含明确的写入信号词。
    防止自动将临时数据、错误、一次性的内容写入长期记忆。

    写入信号词示例：
      "后续默认"  "作为规则"  "架构决策"  "写入 mem0"  "长期记忆"
    """
    msg_lower = message.lower()
    return any(sig.lower() in msg_lower for sig in _WRITE_SIGNALS)


# ── 实体层级分类 ──────────────────────────────────────
# 用于判断一条对话内容应存入 Mem0 的哪个实体层级。
# 返回 "user" | "app" | "agent" 或 None（不写）。


def classify_entity(user_msg: str, assistant_msg: str = "") -> str | None:
    """判断对话内容应存入哪个实体层级。

    返回：
      "user"  — 用户偏好、习惯、环境
      "app"   — 项目规则、架构决策、系统约束
      "agent" — 特定 Agent 的职责边界
      None    — 临时数据，不写 Mem0

    优先级：app > agent > user（越具体越优先）。
    """
    combined = f"{user_msg} {assistant_msg}".lower()

    # ── 明确禁止写入的内容（最高优先级）────────────────
    _skip_signals = [
        "价格", "涨幅", "跌幅", "报价", "最新价",
        "帮我查", "帮我搜", "今天天气", "几点了",
        "traceback", "stack trace",
        "临时", "一次性", "试一下", "测试一下",
    ]
    if any(s in combined for s in _skip_signals):
        return None

    # ── App 级（项目规则、架构、约束）──────────────────
    _app_signals = [
        "项目主链", "数据原则", "架构决策", "架构边界",
        "data pipeline", "collector", "parser", "renderer",
        "禁止", "不允许", "不要绕过", "不要覆盖",
        "必须经过", "必须绑定", "必须标记",
        "阶段", "phase", "milestone", "计划",
        "dashboard", "api", "postgres", "数据库",
        "主链路", "分层", "raw", "parsed", "features",
        "系统约束", "项目规则", "项目原则",
        "历史报告", "覆盖", "原始数据",
    ]
    if any(s in combined for s in _app_signals):
        return "app"

    # ── Run 级（临时会话 / 待整理记录）─────────────────
    # 放在 agent 之前：显式的 "本轮记录" / "会话摘要" 信号
    # 优先级高于主题关键词 (cme/macro 等)
    _run_signals = [
        "临时会话", "临时记录", "待整理", "staging", "session_note",
        "待归档", "草稿", "本轮记录", "会话摘要",
        "助手记录", "临时摘要", "需要整理", "待提升",
    ]
    if any(s in combined for s in _run_signals):
        return "run"

    # ── Agent 级（特定 Agent 职责）─────────────────────
    _agent_signals = [
        "_agent", "agent 规则", "agent 职责", "agent 边界",
        "只负责", "不负责", "岗位说明",
        "risk", "cme", "macro", "positioning",
        "coordinator", "market_odds", "news", "technical",
    ]
    if any(s in combined for s in _agent_signals):
        return "agent"

    # ── User 级（偏好、习惯、环境）─────────────────────
    _user_signals = [
        "我习惯", "我喜欢", "我偏好", "我倾向于",
        "以后回复", "以后用", "以后默认",
        "回答风格", "回复方式", "交流语言",
        "我的环境", "我的项目", "我在用",
        "记住", "保存", "记下来",
    ]
    if any(s in combined for s in _user_signals):
        return "user"

    # 默认不写
    return None
