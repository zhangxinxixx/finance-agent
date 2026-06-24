"""统一数据服务层 — 双源兜底模型。

不新增 CollectorResult / MacroPoint 契约，复用现有模型。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.parsers.macro.models import MacroPoint


@dataclass
class DualSourceResult:
    """双源采集结果 — 合并主源和备用源的数据。

    - points: MacroPoint 列表（来自主源或备用源）
    - source_used: 实际使用的源 ("openbb" | "jin10")
    - unavailable_symbols: 两个源都无法采集的 symbol
    - source_refs: 所有源的溯源信息
    - warnings: 兜底/降级警告
    """

    points: list[MacroPoint] = field(default_factory=list)
    source_used: str | None = None
    unavailable_symbols: list[str] = field(default_factory=list)
    source_refs: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "points": [p.to_dict() for p in self.points],
            "source_used": self.source_used,
            "unavailable_symbols": self.unavailable_symbols,
            "source_refs": self.source_refs,
            "warnings": self.warnings,
        }
