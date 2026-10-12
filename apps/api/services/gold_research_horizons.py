"""Copy time-horizon passages from one verified report; never infer a new bias."""
from __future__ import annotations

import re
from typing import Any

_SHORT_EXPLICIT = re.compile(r"短线分析|短期分析|日内分析|短周期分析")
_LONG_EXPLICIT = re.compile(r"长线分析|长期分析|中长期分析|长周期分析")
_SHORT_BACKGROUND = re.compile(r"黄金价格行为|多周期结构|价格结构|黄金自身承接|未来.*(?:1|一).*(?:3|三).*交易日")
_LONG_BACKGROUND = re.compile(r"周度|长端|实际利率|美债|收益率|就业|通胀|央行|黄金需求|黄金资金|美元|流动性")


def _sections(body: str) -> list[dict[str, str]]:
    """Read top-level report sections, retaining nested headings and original prose."""
    rows: list[dict[str, str]] = []
    title = ""
    lines: list[str] = []
    level = 0
    fence: tuple[str, int] | None = None
    for line in body.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            mark = marker.group(1)
            if fence is None:
                fence = (mark[0], len(mark))
            elif mark[0] == fence[0] and len(mark) >= fence[1] and not line[marker.end():].strip():
                fence = None
            lines.append(line)
            continue
        heading = None if fence else re.match(r"^\s{0,3}(#{2,6})\s+(.+?)\s*#*\s*$", line)
        if heading and (not level or len(heading.group(1)) <= level):
            if title and "\n".join(lines).strip():
                rows.append({"title": title, "content": "\n".join(lines).strip()})
            title, lines, level = heading.group(2), [], len(heading.group(1))
        else:
            lines.append(line)
    if title and "\n".join(lines).strip():
        rows.append({"title": title, "content": "\n".join(lines).strip()})
    return rows


def _lead(content: str, limit: int = 1) -> str:
    # Opening prose is copied, rather than reworded or classified.
    prose: list[str] = []
    fence: tuple[str, int] | None = None
    for line in content.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            mark = marker.group(1)
            if fence is None:
                fence = (mark[0], len(mark))
            elif mark[0] == fence[0] and len(mark) >= fence[1] and not line[marker.end():].strip():
                fence = None
            prose.append("")
        elif fence is None:
            prose.append(line)
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", "\n".join(prose)):
        clean = paragraph.strip()
        if clean.startswith("#") and paragraphs:
            break
        if clean and not clean.startswith(("#", "|", "```", "~~~")):
            paragraphs.append(clean)
            if len(paragraphs) == limit:
                break
    return "\n\n".join(paragraphs)


def project_research_horizons(research: dict[str, Any]) -> dict[str, dict[str, Any]]:
    usable = research.get("status") in {"current", "historical"}
    sections = _sections(research.get("narrative") or "") if usable else []
    results = {}
    for key, horizon, explicit, background in (
        ("short_term", "日内—未来1至3个交易日", _SHORT_EXPLICIT, _SHORT_BACKGROUND),
        ("long_term", "周／月宏观背景", _LONG_EXPLICIT, _LONG_BACKGROUND),
    ):
        selected = [row for row in sections if explicit.search(row["title"])]
        basis = "report_explicit" if selected else "report_excerpt"
        if not selected:
            selected = [row for row in sections if background.search(row["title"])
                        and not (_SHORT_EXPLICIT.search(row["title"]) or _LONG_EXPLICIT.search(row["title"]))
                        and not (key == "long_term" and _SHORT_BACKGROUND.search(row["title"]))]
        summary = _lead(selected[0]["content"], limit=2 if key == "short_term" and basis == "report_excerpt" else 1) if selected else ""
        ready = bool(selected and summary)
        note = ("同一报告的独立周期分析；需按原截止时间核验。" if basis == "report_explicit"
                else "摘录原报告的价格结构与短期路径，未重新分析最新K线。" if key == "short_term"
                else "摘录原报告的宏观背景；原报告未单独给出周／月趋势结论。")
        results[key] = {
            **{field: research.get(field) for field in ("report_id", "run_id", "snapshot_id", "trade_date", "as_of")},
            "status": research["status"] if ready else "unavailable", "horizon": horizon,
            "basis": basis if ready else "unavailable", "summary": summary if ready else "",
            "sections": selected if ready else [],
            "note": note if ready else "本研究尚未提供可分离的周期分析，更新分析后再展示。",
        }
    return results
