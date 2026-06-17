from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MacroPoint:
    symbol: str
    date: str
    value: float
    source: str
    source_url: str
    retrieved_at: str
    raw_path: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CollectorResult:
    points: list[MacroPoint]
    unavailable_symbols: list[str]
    source_refs: list[dict[str, str]]

    def to_dict(self) -> dict[str, object]:
        return {
            "points": [point.to_dict() for point in self.points],
            "unavailable_symbols": self.unavailable_symbols,
            "source_refs": self.source_refs,
        }
