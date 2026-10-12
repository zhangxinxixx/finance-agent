"""Pure key-level lifecycle projection for the daily gold research snapshot.

This module deliberately does not read files, call providers, or decide the
formal Gold Policy state.  Spot levels come only from the technical section;
CME levels stay in futures coordinates and are never converted into spot.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from math import isfinite
from typing import Any, Mapping


def build_key_levels(
    snapshot: dict[str, Any],
    previous_levels: list[dict[str, Any]] | None = None,
    session_quality: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build deterministic spot/CME levels and retain historical stale levels.

    ``previous_levels`` is an already loaded prior output.  A same-day rerun
    can update observations but cannot count as the progressed price window
    required for support/resistance role reversal.
    """

    if not isinstance(snapshot, dict):
        return []
    previous = [deepcopy(item) for item in (previous_levels or []) if isinstance(item, dict)]
    trade_date = _date_text(snapshot.get("trade_date"))
    technical_section = snapshot.get("technical")
    options_section = snapshot.get("options")
    technical = _section_data(technical_section)
    options = _section_data(options_section)
    technical_status = _section_lifecycle_status(technical_section)
    options_status = _section_lifecycle_status(options_section)
    analysis_date = _first_date(
        snapshot.get("analysis_date"),
        snapshot.get("trade_date"),
        snapshot.get("analysis_time"),
        snapshot.get("snapshot_time"),
    )
    observation_date = _first_date(
        technical.get("as_of"),
        technical.get("observation_date"),
        trade_date,
        options.get("trade_date"),
        options.get("as_of"),
        snapshot.get("snapshot_time"),
    )

    current: list[dict[str, Any]] = []
    current.extend(_technical_levels(technical, observation_date, analysis_date, previous, technical_status))
    current.extend(
        _cme_levels(options, observation_date, analysis_date, _cme_refs(snapshot.get("source_refs")), options_status)
    )
    current = apply_session_confidence(
        current,
        session_quality or snapshot.get("session_quality") or snapshot.get("session"),
    )

    current_keys = {_identity(level) for level in current}
    result = current[:]
    for old in previous:
        if _identity(old) in current_keys:
            continue
        preserved = deepcopy(old)
        as_of = analysis_date or observation_date
        if _is_expired(preserved.get("expiry_date"), as_of):
            _invalidate(preserved, as_of)
        elif _lifecycle_status(preserved.get("status")) in {"Stale", "Invalidated"}:
            _apply_lifecycle_gate(preserved, _lifecycle_status(preserved.get("status")), None, as_of)
        else:
            preserved["status"] = "Stale"
            preserved["eligible_for_target"] = False
            preserved["is_target"] = False
            preserved["invalidation"] = "未出现在当前技术滚动窗口或 CME 当前结构中。"
            preserved["valid_until"] = as_of or preserved.get("valid_until")
        for field in (
            "price",
            "instrument",
            "role",
            "source_type",
            "source_date",
            "source_date_explicit",
            "confidence",
            "status",
            "activation",
            "invalidation",
            "valid_until",
            "previous_role",
            "source_refs",
        ):
            preserved.setdefault(field, None)
        result.append(preserved)
    return result


def apply_session_confidence(
    levels: list[dict[str, Any]],
    session_quality: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Apply a session rule only to levels observed in that session.

    A report can be produced on the next calendar day after the OTC daily
    observation (for example a holiday close).  The adjustment therefore uses
    the explicit holiday/observation date when one is available and never
    discounts older rolling-window levels or unrelated CME observations.
    """

    if not isinstance(session_quality, Mapping):
        return levels
    session_class = str(session_quality.get("session_class") or "").upper()
    raw_multiplier = session_quality.get("confidence_multiplier")
    try:
        multiplier = float(raw_multiplier) if raw_multiplier is not None else 0.7 if session_class == "HOLIDAY" else 1.0
    except (TypeError, ValueError):
        multiplier = 0.7 if session_class == "HOLIDAY" else 1.0
    if not isfinite(multiplier) or multiplier <= 0 or multiplier > 1:
        multiplier = 1.0
    adjustment_dates = _session_adjustment_dates(session_quality, session_class)
    result: list[dict[str, Any]] = []
    for item in levels:
        level = deepcopy(item)
        level_date = _first_date(level.get("source_date"))
        # A session discount belongs to an observed spot level from that
        # session.  ``evaluation_date``/``window_end`` describe when a
        # rolling calculation was evaluated, and CME levels describe a
        # futures report; neither is evidence that the level itself was
        # observed in the holiday session.
        is_spot_technical_level = (
            str(level.get("instrument") or "").lower() in {"xauusd spot", "xauusd_spot", "spot"}
            and level.get("source_type") == "technical.key_levels"
        )
        should_adjust = (
            multiplier != 1.0
            and is_spot_technical_level
            and level.get("source_date_explicit") is True
            and level_date is not None
            and level_date in adjustment_dates
        )
        if not should_adjust:
            result.append(level)
            continue
        confidence = _confidence(level.get("base_confidence", level.get("confidence")), 0.0)
        level["base_confidence"] = confidence
        level["confidence_multiplier"] = multiplier
        level["session_confidence_applied"] = True
        level["session_adjustment_date"] = level_date
        level["confidence"] = round(confidence * multiplier, 6)
        level["session_class"] = session_class or None
        level["confidence_note"] = (
            "holiday level confidence multiplied by 0.7; rule coefficient, not statistical probability"
            if multiplier == 0.7 and session_class == "HOLIDAY"
            else "session confidence adjustment is a deterministic rule, not a statistical probability"
        )
        result.append(level)
    return result


def _session_adjustment_dates(session_quality: Mapping[str, Any], session_class: str) -> set[str]:
    """Return dates explicitly identified as the holiday/observed session."""

    if session_class != "HOLIDAY":
        return {
            parsed
            for parsed in (_first_date(session_quality.get("trade_date"), session_quality.get("session_date")),)
            if parsed
        }
    values: list[Any] = [
        session_quality.get("holiday_date"),
        session_quality.get("observed_holiday_date"),
        session_quality.get("session_date"),
    ]
    entry = session_quality.get("calendar_entry")
    if isinstance(entry, Mapping):
        values.append(entry.get("date") or entry.get("trade_date"))
    for key in ("otc_daily_close", "otc"):
        observation = session_quality.get(key)
        if isinstance(observation, Mapping):
            values.append(observation.get("observation_date"))
    dates = {_date for value in values if (_date := _first_date(value))}
    if dates:
        return dates
    fallback = _first_date(session_quality.get("trade_date"))
    return {fallback} if fallback else set()


def _technical_levels(
    technical: dict[str, Any],
    observation_date: str | None,
    analysis_date: str | None,
    previous: list[dict[str, Any]],
    section_status: str | None,
) -> list[dict[str, Any]]:
    raw_levels = technical.get("key_levels")
    if not isinstance(raw_levels, list):
        raw_levels = []
    refs = _refs(technical.get("source_refs"))
    levels: list[dict[str, Any]] = []
    for raw in raw_levels:
        if not isinstance(raw, dict):
            continue
        price = _number(raw.get("price"))
        if price is None:
            continue
        kind = str(raw.get("kind") or raw.get("role") or "technical_level")
        base_role = _spot_role(raw, kind)
        # Only an explicit date can establish when a level was observed.  A
        # rolling window's ``window_end``/technical ``as_of`` is an
        # evaluation boundary, not the date of its high/low.
        source_date = _first_date(raw.get("date"), raw.get("source_date"))
        source_date_explicit = source_date is not None
        evaluation_date = _first_date(raw.get("evaluation_date"), raw.get("window_end"), observation_date)
        source_refs = _refs(raw.get("source_refs")) or refs
        level = _make_level(
            price=price,
            instrument="XAUUSD spot",
            role=base_role,
            source_type="technical.key_levels",
            source_date=source_date,
            source_date_explicit=source_date_explicit,
            confidence=_confidence(raw.get("confidence"), 0.65 if source_refs else 0.5),
            status="Active",
            activation=f"技术关键位 {kind} 已由现货窗口登记。",
            invalidation="完整收盘确认突破或该水平离开当前有效窗口。",
            valid_until=raw.get("valid_until"),
            source_refs=source_refs,
            evaluation_date=evaluation_date,
            window_end=raw.get("window_end"),
            identity=("technical.key_levels", kind, source_date, price),
        )
        raw_status = str(raw.get("status") or "").lower()
        upstream_status = _lifecycle_status(raw_status) or section_status
        future_status = _future_date_status((source_date, evaluation_date), analysis_date)
        matched = _match_previous(level, previous)
        if raw_status == "broken_on_close":
            level["status"] = "Conditional"
            level["activation"] = f"{evaluation_date or source_date} 收盘突破窗口边界，等待推进窗口确认反转。"
            level["invalidation"] = "后续窗口未延续突破，或收盘重新回到原结构一侧。"
            old_role = str(matched.get("role")) if matched else ""
            if (
                not upstream_status
                and not future_status
                and matched
                and matched.get("status") in {"Active", "Conditional"}
                and old_role in {"support", "resistance"}
                and old_role != base_role
            ):
                # The level was already reversed in an earlier window.  A
                # later broken_on_close for the same raw support/resistance
                # must keep that role; it must never toggle back and forth.
                level["role"] = old_role
                level["previous_role"] = matched.get("previous_role") or base_role
                level["status"] = "Active"
                level["activation"] = f"{evaluation_date or source_date} 延续已确认的 {old_role} 反转角色，不重复切换。"
            elif (
                not upstream_status
                and not future_status
                and matched
                and matched.get("status") in {"Active", "Conditional"}
                and _progressed(matched, evaluation_date)
                and old_role == base_role
            ):
                level["role"] = "resistance" if old_role == "support" else "support"
                level["previous_role"] = old_role
                level["status"] = "Active"
                level["activation"] = f"{evaluation_date} 新价格窗口确认 {old_role} -> {level['role']} 反转。"
        elif raw_status in {"reclaimed_after_intraday_breach", "rejected_after_intraday_breach"}:
            level["activation"] = f"{evaluation_date or source_date} 盘中越界后收盘收回/拒绝，原角色保持。"
        _apply_lifecycle_gate(level, upstream_status, future_status, analysis_date)
        levels.append(level)

    ma20 = _number(technical.get("ma20"))
    if ma20 is not None:
        source_refs = refs
        level = _make_level(
            price=ma20,
            instrument="XAUUSD spot",
            role="pivot",
            source_type="technical.ma20",
            source_date=observation_date,
            source_date_explicit=False,
            confidence=_confidence(technical.get("ma20_confidence"), 0.6 if source_refs else 0.45),
            status="Active",
            activation="MA20 作为现货趋势过滤和枢轴参考。",
            invalidation="MA20 不再由有效技术快照计算。",
            valid_until=None,
            source_refs=source_refs,
            evaluation_date=observation_date,
            identity=("technical.ma20", "pivot", observation_date, ma20),
        )
        matched = _match_previous(level, previous)
        if matched and matched.get("status") == "Invalidated":
            level["previous_role"] = matched.get("role")
        _apply_lifecycle_gate(
            level,
            section_status,
            _future_date_status((observation_date,), analysis_date),
            analysis_date,
        )
        levels.append(level)
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for level in levels:
        key = _identity(level)
        if key in seen:
            continue
        seen.add(key)
        unique.append(level)
    return unique


def _cme_levels(
    options: dict[str, Any],
    observation_date: str | None,
    analysis_date: str | None,
    snapshot_refs: list[dict[str, Any]],
    section_status: str | None,
) -> list[dict[str, Any]]:
    if not options:
        return []
    params = options.get("parameters") if isinstance(options.get("parameters"), dict) else {}
    forward = params.get("forward_by_expiry") if isinstance(params.get("forward_by_expiry"), dict) else {}
    expiry_sources = params.get("expiry_sources") if isinstance(params.get("expiry_sources"), dict) else {}
    if not expiry_sources:
        audit = options.get("audit") if isinstance(options.get("audit"), dict) else {}
        expiry_sources = audit.get("black76_audit") if isinstance(audit.get("black76_audit"), dict) else {}
    source_refs = _cme_refs([*_refs(options.get("source_refs")), *_refs(options.get("source_trace")), *snapshot_refs])
    data_source = options.get("data_source") if isinstance(options.get("data_source"), dict) else {}
    options_date = _first_date(
        data_source.get("report_date"), options.get("report_date"), options.get("trade_date"), observation_date
    )
    as_of = analysis_date or observation_date
    upstream_status = (
        section_status or _lifecycle_status(options.get("status")) or _lifecycle_status(data_source.get("status"))
    )
    future_status = _future_date_status((options_date,), as_of)
    levels: list[dict[str, Any]] = []

    for side, role in (("support", "support"), ("resistance", "resistance")):
        for item in _items(
            options.get("support_resistance", {}).get(side)
            if isinstance(options.get("support_resistance"), dict)
            else []
        ):
            level = _cme_level_from_item(
                item, role, options_date, as_of, forward, expiry_sources, source_refs, upstream_status, future_status
            )
            if level:
                levels.append(level)
    for item in _items(options.get("wall_scores")):
        side = str(item.get("side") or item.get("dominant_side") or item.get("wall_type") or "").lower()
        role = (
            "resistance"
            if "call" in side or "resistance" in side
            else "support"
            if "put" in side or "support" in side
            else "oi_wall"
        )
        if _number(item.get("net_gex")) is not None or _number(item.get("gex")) is not None:
            role = "gamma_wall" if role == "oi_wall" else role
        level = _cme_level_from_item(
            item, role, options_date, as_of, forward, expiry_sources, source_refs, upstream_status, future_status
        )
        if level:
            levels.append(level)

    for item in _max_pain_items(options):
        price = _number(item.get("price", item.get("strike", item.get("max_pain"))))
        if price is None:
            continue
        expiry = item.get("expiry") or item.get("contract")
        expiry_date, expiry_source, estimated = _expiry_info(expiry, item, forward, expiry_sources)
        level_refs = _cme_refs([*_refs(item.get("source_refs")), *source_refs])
        level = _make_level(
            price=price,
            instrument="GC futures",
            role="soft_anchor",
            source_type="cme.options.max_pain",
            source_date=options_date,
            confidence=_confidence(item.get("confidence"), 0.4),
            status="Conditional" if estimated or not level_refs else "Active",
            activation="Max Pain 仅作为临近到期的软锚，不作为硬目标。",
            invalidation="到期、OI 结构不完整或重大事件使软锚失效。",
            valid_until=expiry_date,
            source_refs=level_refs,
            evaluation_date=options_date,
            expiry=expiry,
            expiry_date=expiry_date,
            expiry_source=expiry_source,
            expiry_estimated=estimated,
            soft_anchor=True,
            eligible_for_target=False,
            is_target=False,
            identity=("cme.options.max_pain", expiry, price),
        )
        _apply_lifecycle_gate(level, _lifecycle_status(item.get("status")) or upstream_status, future_status, as_of)
        if _is_expired(expiry_date, as_of):
            _invalidate(level, as_of)
        levels.append(level)
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for level in levels:
        key = _identity(level)
        if key in seen:
            continue
        seen.add(key)
        unique.append(level)
    return unique


def _cme_level_from_item(
    item: dict[str, Any],
    role: str,
    source_date: str | None,
    analysis_date: str | None,
    forward: dict[str, Any],
    expiry_sources: dict[str, Any],
    refs: list[dict[str, Any]],
    upstream_status: str | None,
    future_status: str | None,
) -> dict[str, Any] | None:
    price = _number(item.get("strike", item.get("price", item.get("level"))))
    if price is None:
        return None
    expiry = item.get("expiry") or item.get("contract")
    expiry_date, expiry_source, estimated = _expiry_info(expiry, item, forward, expiry_sources)
    level_refs = _cme_refs([*_refs(item.get("source_refs")), *refs])
    status = "Conditional" if estimated or expiry_date is None or not level_refs else "Active"
    level = _make_level(
        price=price,
        instrument="GC futures",
        role=role,
        source_type="cme.options.wall",
        source_date=source_date,
        confidence=_confidence(item.get("confidence", item.get("wall_score")), 0.5),
        status=status,
        activation="CME 期货坐标的 OI/GEX 结构墙，仅用于期货结构观察。",
        invalidation="OI/GEX 结构迁移、合同失效或到期。",
        valid_until=expiry_date,
        source_refs=level_refs,
        evaluation_date=source_date,
        expiry=expiry,
        expiry_date=expiry_date,
        expiry_source=expiry_source,
        expiry_estimated=estimated,
        coordinate="futures",
        eligible_for_target=status == "Active",
        is_target=status == "Active",
        identity=("cme.options.wall", expiry, role, price),
    )
    _apply_lifecycle_gate(level, _lifecycle_status(item.get("status")) or upstream_status, future_status, analysis_date)
    if _is_expired(expiry_date, analysis_date):
        _invalidate(level, analysis_date)
    return level


def _expiry_info(
    expiry: Any, item: dict[str, Any], forward: dict[str, Any], sources: dict[str, Any]
) -> tuple[str | None, str | None, bool]:
    key = str(expiry) if expiry is not None else ""
    candidates = [item, sources.get(key), forward.get(key)]
    expiry_date = None
    source = None
    estimated = False
    for candidate in candidates:
        if isinstance(candidate, str):
            source = source or candidate
            estimated = estimated or "estimated" in candidate.lower()
            continue
        if not isinstance(candidate, dict):
            continue
        expiry_date = expiry_date or _date_text(candidate.get("expiry_date") or candidate.get("actual_expiry_date"))
        source = source or _text(
            candidate.get("expiry_source") or candidate.get("expiry_date_source") or candidate.get("source")
        )
        estimated_value = candidate.get(
            "expiry_estimated", candidate.get("expiry_date_estimated", candidate.get("estimated_expiry"))
        )
        estimated = estimated or bool(estimated_value) or "estimated" in str(source or "").lower()
    return expiry_date, source, estimated


def _max_pain_items(options: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[Any] = []
    for key in ("max_pain", "max_pain_by_expiry"):
        value = options.get(key)
        if isinstance(value, dict):
            for expiry, item in value.items():
                if isinstance(item, dict):
                    values.append({**item, "expiry": item.get("expiry") or expiry})
                elif item is not None:
                    values.append({"price": item, "expiry": expiry})
        elif isinstance(value, list):
            values.extend(value)
        elif value is not None:
            values.append({"price": value})
    params = options.get("parameters")
    if isinstance(params, dict) and params.get("max_pain") is not None:
        values.append(params["max_pain"] if isinstance(params["max_pain"], dict) else {"price": params["max_pain"]})
    return [dict(item) for item in values if isinstance(item, dict)]


def _make_level(
    *,
    price: float,
    instrument: str,
    role: str,
    source_type: str,
    source_date: str | None,
    confidence: float,
    status: str,
    activation: str,
    invalidation: str,
    valid_until: Any,
    source_refs: list[dict[str, Any]],
    evaluation_date: str | None,
    identity: tuple[Any, ...],
    previous_role: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    eligible_for_target = extra.pop("eligible_for_target", status == "Active")
    is_target = extra.pop("is_target", status == "Active")
    if status != "Active":
        eligible_for_target = False
        is_target = False
    return {
        "price": price,
        "instrument": instrument,
        "role": role,
        "source_type": source_type,
        "source_date": source_date,
        "confidence": confidence,
        "status": status,
        "activation": activation,
        "invalidation": invalidation,
        "valid_until": _date_text(valid_until),
        "previous_role": previous_role,
        "source_refs": deepcopy(source_refs),
        "evaluation_date": evaluation_date,
        "eligible_for_target": eligible_for_target,
        "is_target": is_target,
        "_identity": identity,
        **extra,
    }


def _apply_lifecycle_gate(
    level: dict[str, Any],
    upstream_status: str | None,
    future_status: str | None,
    as_of: str | None,
) -> None:
    """Apply source/date quality before a level can become a target."""

    status = upstream_status or future_status
    if status:
        level["status"] = status
        level["eligible_for_target"] = False
        level["is_target"] = False
        level["valid_until"] = level.get("valid_until") or as_of
        if status == "Stale":
            level["invalidation"] = "上游数据标记为 stale，当前仅保留观察，不参与目标。"
        elif status == "Invalidated":
            level["invalidation"] = "上游数据标记为 invalidated/expired，当前不参与目标。"
        else:
            level["invalidation"] = "来源日期晚于分析日或上游数据尚未完成确认，当前仅作 Conditional 观察。"
    _sync_target_flags(level)


def _sync_target_flags(level: dict[str, Any]) -> None:
    if level.get("status") != "Active":
        level["eligible_for_target"] = False
        level["is_target"] = False


def _lifecycle_status(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"stale", "outdated", "out_of_date"}:
        return "Stale"
    if normalized in {"invalidated", "invalid", "void", "revoked", "expired", "expiry"}:
        return "Invalidated"
    if normalized in {"unavailable", "blocked", "failed", "error", "partial", "degraded"}:
        return "Conditional"
    return None


def _future_date_status(values: tuple[Any, ...], as_of: str | None) -> str | None:
    current = _date_text(as_of)
    if not current:
        return None
    if any(value and (parsed := _date_text(value)) and parsed > current for value in values):
        return "Conditional"
    return None


def _section_lifecycle_status(section: Any) -> str | None:
    if not isinstance(section, dict):
        return None
    data = section.get("data")
    values = [section.get("status")]
    if isinstance(data, dict):
        values.append(data.get("status"))
    for value in values:
        status = _lifecycle_status(value)
        if status:
            return status
    return None


def _spot_role(raw: dict[str, Any], kind: str) -> str:
    role = str(raw.get("role") or "").lower()
    if role in {"support", "resistance", "pivot", "event_low", "event_high"}:
        return role
    value = kind.lower()
    if "low" in value:
        return "event_low" if "daily" in value else "support"
    if "high" in value:
        return "event_high" if "daily" in value else "resistance"
    return "pivot"


def _match_previous(level: dict[str, Any], previous: list[dict[str, Any]]) -> dict[str, Any] | None:
    identity = level.get("_identity")
    for old in previous:
        if _identity(old) == identity:
            return old
    return None


def _identity(level: dict[str, Any]) -> tuple[Any, ...]:
    identity = level.get("_identity")
    if isinstance(identity, (list, tuple)):
        return tuple(identity)
    source = level.get("source_type")
    expiry = level.get("expiry")
    price = _number(level.get("price"))
    if str(source).startswith("cme"):
        return (source, expiry, level.get("role"), price)
    return (source, level.get("source_date"), price)


def _progressed(previous: dict[str, Any], current_date: str | None) -> bool:
    old_date = _first_date(previous.get("evaluation_date"), previous.get("window_end"), previous.get("source_date"))
    return bool(current_date and old_date and current_date > old_date)


def _invalidate(level: dict[str, Any], as_of: str | None) -> None:
    level["status"] = "Invalidated"
    level["eligible_for_target"] = False
    level["is_target"] = False
    level["valid_until"] = level.get("valid_until") or as_of
    level["invalidation"] = "期权合约已过期，不再参与当前目标。"


def _is_expired(value: Any, as_of: str | None) -> bool:
    expiry, current = _date_text(value), _date_text(as_of)
    return bool(expiry and current and expiry <= current)


def _section_data(section: Any) -> dict[str, Any]:
    if not isinstance(section, dict):
        return {}
    data = section.get("data")
    return data if isinstance(data, dict) else section


def _items(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _refs(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _cme_refs(values: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in values or []:
        text = " ".join(
            str(ref.get(key, ""))
            for key in ("source", "name", "provider", "dataset", "source_url", "raw_path", "reference")
        ).lower()
        if "cme" not in text and "cmegroup" not in text:
            continue
        marker = repr(sorted(ref.items()))
        if marker not in seen:
            seen.add(marker)
            refs.append(ref)
    return refs


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number > 0 else None


def _confidence(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number if isfinite(number) else default))


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _date_text(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _first_date(*values: Any) -> str | None:
    for value in values:
        parsed = _date_text(value)
        if parsed:
            return parsed
    return None


__all__ = ["apply_session_confidence", "build_key_levels"]
