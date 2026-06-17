"""项目主线记忆类型定义。

定义 ProjectMemoryType 枚举和 ProjectMemoryRecord 数据模型。
所有项目主线记忆必须通过此模型录入，保证结构统一。
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ProjectMemoryType(StrEnum):
    """项目主线记忆类型。

    每种类型对应一类项目上下文信息，用于分类检索和过滤。
    禁止在此枚举中混入金融分析业务相关类型（如 market_event、trade_signal 等）。
    """

    PROJECT_VISION = "project_vision"           # 项目定位
    PROJECT_PRINCIPLE = "project_principle"     # 项目原则
    CURRENT_PHASE = "current_phase"             # 当前阶段
    CURRENT_PRIORITY = "current_priority"       # 当前优先级
    ARCHITECTURE_DECISION = "architecture_decision"  # 架构决策
    FRONTEND_DIRECTION = "frontend_direction"   # 前端方向
    BACKEND_DIRECTION = "backend_direction"     # 后端方向
    AGENT_RULE = "agent_rule"                   # Agent 规则
    BLOCKER = "blocker"                         # 当前卡点
    NEXT_ACTION = "next_action"                 # 下一步动作
    ERROR_PATTERN = "error_pattern"             # 错误模式
    USER_FEEDBACK = "user_feedback"             # 用户反馈


class ProjectMemoryRecord(BaseModel):
    """项目主线记忆记录。

    所有字段必填（除 metadata 外），确保记忆可追溯、可检索。
    """

    user_id: str = "xinxi"
    project_id: str = "finance_analysis_system"
    memory_type: ProjectMemoryType
    content: str = Field(..., min_length=1, description="记忆内容摘要，不宜过长")
    tags: list[str] = Field(default_factory=list, description="分类标签，如 ['frontend', 'phase1']")
    importance: str = Field(
        default="medium",
        description="重要性：low / medium / high",
        pattern=r"^(low|medium|high)$",
    )
    source: str = Field(
        default="manual",
        description="来源：manual / hermes_execution / user_feedback / code_review",
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")
