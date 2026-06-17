"""News snapshot — filter & classify economic calendar + flash headlines.

Processes ``MacroPoint`` entries keyed as ``NEWS_EVENT:<title>`` and
``NEWS_FLASH`` into a structured ``NewsSnapshot``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class CalendarEvent:
    title: str
    pub_time: str          # ISO datetime string
    star: int              # importance 1-5
    actual: str = ""
    consensus: str = ""
    previous: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FlashHeadline:
    time: str              # ISO datetime string
    content: str           # truncated to 200 chars
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NewsSnapshot:
    as_of: str
    recent_events: list[CalendarEvent] = field(default_factory=list)
    recent_flashes: list[FlashHeadline] = field(default_factory=list)
    risk_level: str = "LOW"           # HIGH / MEDIUM / LOW
    high_star_count_7d: int = 0       # number of ★4+ events in last/next 7d
    source_refs: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "recent_events": [e.to_dict() for e in self.recent_events],
            "recent_flashes": [f.to_dict() for f in self.recent_flashes],
            "risk_level": self.risk_level,
            "high_star_count_7d": self.high_star_count_7d,
            "source_refs": self.source_refs,
        }


def build_news_snapshot(
    points: list[dict[str, Any]],
    *,
    as_of: str,
    source_refs: list[dict[str, str]] | None = None,
) -> NewsSnapshot:
    """Build a NewsSnapshot from collected MacroPoints.

    Extracts calendar events (``NEWS_EVENT:*``) and flash headlines
    (``NEWS_FLASH``) from the point list, deduplicates by content, and
    computes a composite risk_level based on recent high-impact events
    and keyword-rich flash volume.
    """
    events: list[CalendarEvent] = []
    flash_seen: set[str] = set()
    flashes: list[FlashHeadline] = []

    for point in points:
        symbol = str(point.get("symbol", ""))
        if symbol.startswith("NEWS_EVENT:"):
            events.append(CalendarEvent(
                title=symbol[len("NEWS_EVENT:"):],
                pub_time=str(point.get("date", "")),
                star=int(float(str(point.get("value", "0")))) if point.get("value") is not None else 0,
            ))
        elif symbol == "NEWS_FLASH":
            # MacroPoint has source_url but not content. Content is in raw payload only.
            # We use source_url as a unique key to deduplicate (same flash may appear
            # in list_flash and search_flash results).
            url = str(point.get("source_url", ""))
            time_str = str(point.get("date", ""))
            key = f"{time_str}|{url}"
            if key in flash_seen:
                continue
            flash_seen.add(key)
            flashes.append(FlashHeadline(
                time=time_str,
                content="",   # content is in raw payload, not in MacroPoint
                url=url,
            ))

    # ── Recent events (last 7 days) ──────────────────────────────────
    try:
        now = datetime.fromisoformat(as_of) if "T" in as_of else datetime.now(timezone.utc)
    except (ValueError, TypeError):
        now = datetime.now(timezone.utc)

    cutoff_ago = (now - timedelta(days=7)).isoformat()
    recent = [
        e for e in events
        if e.pub_time >= cutoff_ago
    ]

    # ── Risk level ────────────────────────────────────────────────────
    high_star = sum(1 for e in recent if e.star >= 4)
    risk_level = "LOW"

    # Keywords in flash URLs can signal risk intensity
    high_risk_url_markers = {"非农", "CPI", "PCE", "利率决议", "FOMC", "加息", "降息"}
    flash_risk_hits = sum(
        1 for f in flashes
        if any(kw in f.url for kw in high_risk_url_markers)
    )
    flash_volume = len(flashes)

    if high_star >= 2 or (high_star >= 1 and flash_risk_hits >= 3):
        risk_level = "HIGH"
    elif high_star >= 1 or flash_risk_hits >= 2 or flash_volume > 100:
        risk_level = "MEDIUM"

    return NewsSnapshot(
        as_of=as_of,
        recent_events=sorted(recent, key=lambda e: e.pub_time, reverse=True),
        recent_flashes=flashes[:20],   # keep top 20 deduplicated
        risk_level=risk_level,
        high_star_count_7d=high_star,
        source_refs=list(source_refs or []),
    )
