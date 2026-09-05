"""Deterministic, non-executing suggestions for Gold input gaps.

The data-control layer can point a reviewer at an existing producer, but it
does not turn that pointer into a worker task.  Existing producers do not
accept the Gold cutoff as an execution contract, so every known mapping stays
manual until a caller supplies the missing window decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.data_control.gold_processing_context import GoldProcessingContext


MACRO_GAP_LABELS = frozenset(
    {
        "US02Y",
        "US10Y",
        "US30Y",
        "T10YIE",
        "BROAD_DOLLAR",
        "DGS2",
        "DGS10",
        "DGS30",
        "DTWEXBGS",
    }
)
REAL10Y_GAP_LABELS = frozenset(
    {
        "REAL10Y_ESTIMATED",
    }
)
XAU_GAP_LABELS = frozenset(
    {
        "XAUUSD",
        "XAUUSD_SPOT",
        "XAUUSD_PRICE",
        "MARKET_PRICES_XAUUSD_SPOT",
        "TECHNICAL_XAUUSD",
    }
)
_OPTIONS_REASONS = frozenset({"OPTIONS_INPUT_UNUSABLE", "OPTIONS_INPUT_DEGRADED"})
_OPTIONS_GAP_LABELS = frozenset({"CME_OPTIONS", "CME_GC_OPTIONS_REGIME", "OPTIONS"})
_REAL_DERIVATION_REASONS = frozenset(
    {
        "REAL10Y_ESTIMATED_CORE_INPUT_UNUSABLE",
        "REAL10Y_ESTIMATED_AS_OF_MISMATCH",
    }
)
_UNSUPPORTED_REASON_CODES = frozenset(
    {
        "OFFICIAL_EVENT_SNAPSHOT_UNUSABLE",
        "OFFICIAL_EVENT_SNAPSHOT_DEGRADED",
    }
)
_GAP_REASON_RE = re.compile(r"^(?:REQUIRED|CONFIRMATORY)_INPUT_(?:UNUSABLE|DEGRADED):(.+)$")


def build_gold_gap_actions(context: GoldProcessingContext) -> list[dict[str, Any]]:
    """Build stable review actions from one validated Gold context.

    The projection only reads the validated context; it never reads storage or
    calls a producer.
    """

    lineage = _lineage(context)
    if not context.found:
        reason = _string(context.authority_reason_code) or "gold_authority_unavailable"
        return [
            _action(
                group="authority",
                labels=("gold_premarket_authority",),
                reason_codes=(reason,),
                lineage=lineage,
                producer=None,
                handler=None,
                steps=(),
                status="unsupported",
                action="diagnose",
                action_reason_code="authority_unavailable",
                limitations=("Gold authority is unavailable or invalid; no producer is inferred.",),
            )
        ]

    groups: dict[str, dict[str, list[str]]] = {
        "macro": {"labels": [], "reasons": []},
        "xauusd": {"labels": [], "reasons": []},
        "cme": {"labels": [], "reasons": []},
        "unsupported": {"labels": [], "reasons": []},
    }
    labels = _gap_labels(context)
    reasons = _reason_codes(context)
    options_readiness = _string(context.options_readiness) or "blocked"
    cme_allowed = bool(_OPTIONS_REASONS.intersection(reasons)) and options_readiness in {
        "blocked",
        "observe",
        "degraded",
    }

    for label in labels:
        group = _classify_label(label)
        if group == "cme":
            # CME is intentionally reason-gated below.  A prohibited output or
            # an arbitrary options label cannot invent a bulletin producer.
            _append_group(groups["cme"] if cme_allowed else groups["unsupported"], label=label)
            continue
        if group == "real10y":
            group = "unsupported"
        _append_group(groups[group], label=label)

    for reason in reasons:
        if reason in _OPTIONS_REASONS:
            if options_readiness in {"blocked", "observe", "degraded"}:
                _append_group(groups["cme"], reason=reason)
            continue
        if reason in _REAL_DERIVATION_REASONS:
            _append_group(groups["unsupported"], label="REAL10Y_ESTIMATED", reason=reason)
            continue
        match = _GAP_REASON_RE.match(reason)
        if match:
            label = match.group(1)
            group = _classify_label(label)
            if group == "cme" and not cme_allowed:
                group = "unsupported"
            _append_group(groups["unsupported"] if group == "real10y" else groups[group], label=label, reason=reason)
            continue
        if reason in _UNSUPPORTED_REASON_CODES:
            _append_group(groups["unsupported"], label=reason, reason=reason)

    actions: list[dict[str, Any]] = []
    if groups["macro"]["labels"]:
        actions.append(
            _action(
                group="macro",
                labels=groups["macro"]["labels"],
                reason_codes=groups["macro"]["reasons"],
                lineage=lineage,
                producer="macro_collect",
                handler="apps.worker.pipelines.macro.run_macro_step",
                steps=("macro_collect", "macro_feature"),
                status="manual_required",
                action="refresh_inputs",
                action_reason_code="macro_window_not_precise",
                limitations=(
                    "macro_collect uses the current UTC date and has no Gold cutoff or per-symbol window contract.",
                    "macro_feature must follow macro_collect; report_render remains a pipeline reference only.",
                ),
                extra={
                    "pipeline_reference": ["macro_collect", "macro_feature", "report_render"],
                    "window": {
                        "mode": "current_utc_date_only",
                        "requested_cutoff": lineage["cutoff"],
                        "precise": False,
                    },
                },
            )
        )
    if groups["cme"]["reasons"]:
        actions.append(
            _action(
                group="cme",
                labels=groups["cme"]["labels"] or ("CME_GC_OPTIONS_REGIME",),
                reason_codes=groups["cme"]["reasons"],
                lineage=lineage,
                producer="cme_download",
                handler="apps.worker.pipelines.cme.run_cme_step",
                steps=("cme_download", "cme_parse", "cme_ingest", "option_wall"),
                status="manual_required",
                action="refresh_options_input",
                action_reason_code="cme_window_not_precise",
                limitations=(
                    "The CME pipeline uses the current Daily Bulletin and has no requested Gold cutoff/date contract.",
                    "PRELIM or older bulletin evidence stays degraded; this suggestion cannot upgrade it.",
                ),
                extra={
                    "pipeline_reference": ["cme_download", "cme_parse", "cme_ingest", "option_wall"],
                    "window": {
                        "mode": "latest_bulletin",
                        "requested_cutoff": lineage["cutoff"],
                        "precise": False,
                    },
                },
            )
        )
    if groups["xauusd"]["labels"]:
        actions.append(
            _action(
                group="xauusd",
                labels=groups["xauusd"]["labels"],
                reason_codes=groups["xauusd"]["reasons"],
                lineage=lineage,
                producer="twelvedata_xauusd_dispatch",
                handler="apps.scheduler.twelvedata_refresh.refresh_due_twelvedata_xauusd",
                steps=("twelvedata_xauusd_dispatch",),
                status="manual_required",
                action="refresh_price_input",
                action_reason_code="xauusd_due_window_not_precise",
                limitations=(
                    "The scheduler selects due intervals from its current clock and only closed latest bars.",
                    "Twelve Data is a validation/fallback identity and this suggestion does not release the core price gate.",
                ),
                extra={
                    "window": {
                        "mode": "scheduler_due_latest",
                        "supported_intervals": ["5min", "15min", "1h", "4h"],
                        "requested_cutoff": lineage["cutoff"],
                        "precise": False,
                    },
                    "provider_identity": "twelvedata_xauusd",
                },
            )
        )
    if groups["unsupported"]["labels"]:
        real10y_diagnostic = any(_classify_label(label) == "real10y" for label in groups["unsupported"]["labels"])
        actions.append(
            _action(
                group="unsupported",
                labels=groups["unsupported"]["labels"],
                reason_codes=groups["unsupported"]["reasons"],
                lineage=lineage,
                producer=None,
                handler=None,
                steps=(),
                status="unsupported",
                action="diagnose",
                action_reason_code=(
                    "real10y_derivation_or_alignment_required"
                    if real10y_diagnostic
                    else "gold_gap_unsupported"
                ),
                limitations=(
                    (
                        "REAL10Y_ESTIMATED is derived from US10Y and T10YIE; "
                        "inspect computation and timestamp alignment."
                    ),
                    "No recollection producer is claimed for a missing derived value.",
                )
                if real10y_diagnostic
                else ("No approved producer or precise processing contract exists for this Gold gap.",),
            )
        )
    return actions


def _action(
    *,
    group: str,
    labels: Sequence[str],
    reason_codes: Sequence[str],
    lineage: dict[str, Any],
    producer: str | None,
    handler: str | None,
    steps: Sequence[str],
    status: str,
    action: str,
    action_reason_code: str,
    limitations: Sequence[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_labels = _unique_strings(labels)
    clean_reasons = _unique_strings(reason_codes)
    request_id = _request_id(
        group=group,
        labels=clean_labels,
        reason_codes=clean_reasons,
        lineage=lineage,
    )
    ordered_steps = [str(step) for step in steps]
    result: dict[str, Any] = {
        "request_id": request_id,
        "input": "gold_gap",
        "gap_group": group,
        "gap_labels": clean_labels,
        "producer": producer,
        "handler": handler,
        "steps": ordered_steps,
        "task_keys": list(ordered_steps),
        "ready_steps": [],
        "status": status,
        "action": action,
        "dispatchable": False,
        "auto_execute": False,
        "reason_code": clean_reasons[0] if clean_reasons else action_reason_code,
        "reason_codes": clean_reasons,
        "source_reason_codes": clean_reasons,
        "action_reason_code": action_reason_code,
        "limitations": list(limitations),
        "required_for": clean_labels,
        "lineage": dict(lineage),
    }
    if extra:
        result.update(dict(extra))
    return result


def _lineage(context: GoldProcessingContext) -> dict[str, Any]:
    source_refs = [dict(ref) for ref in context.source_refs() if ref]
    return {
        "authority": {
            "status": _string(context.authority_status),
            "reason_code": _string(context.authority_reason_code),
            "snapshot_id": _string(context.authority_snapshot_id),
            "run_id": _string(context.authority_run_id),
        },
        "feature": {
            "snapshot_id": _string(context.feature_snapshot_id),
            "payload_hash": _string(context.feature_payload_hash),
        },
        "cutoff": context.cutoff.isoformat() if context.cutoff else None,
        "artifact": {
            "path": _string(context.artifact_path),
            "sha256": _string(context.artifact_sha256),
        },
        "source_refs": source_refs,
    }


def _gap_labels(context: GoldProcessingContext) -> list[str]:
    return _unique_strings((*context.missing_required_inputs, *context.missing_confirmatory_inputs))


def _reason_codes(context: GoldProcessingContext) -> list[str]:
    return _unique_strings(context.reason_codes)


def _classify_label(label: str) -> str:
    normalized = _normalize(label)
    if _contains_jin10(normalized):
        return "unsupported"
    if normalized in _OPTIONS_GAP_LABELS:
        return "cme"
    if normalized in MACRO_GAP_LABELS:
        return "macro"
    if normalized in REAL10Y_GAP_LABELS:
        return "real10y"
    if normalized in XAU_GAP_LABELS:
        return "xauusd"
    return "unsupported"


def _contains_jin10(value: str) -> bool:
    return "JIN10" in value or "JIN_10" in value


def _normalize(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value).strip().upper()).strip("_")


def _append_group(group: dict[str, list[str]], *, label: str | None = None, reason: str | None = None) -> None:
    if label and label not in group["labels"]:
        group["labels"].append(label)
    if reason and reason not in group["reasons"]:
        group["reasons"].append(reason)


def _unique_strings(values: Sequence[str] | Any) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value).strip()))


def _request_id(*, group: str, labels: Sequence[str], reason_codes: Sequence[str], lineage: dict[str, Any]) -> str:
    identity = {
        "group": group,
        "labels": sorted(_normalize(label) for label in labels),
        "reason_codes": sorted(str(reason) for reason in reason_codes),
        "authority": lineage.get("authority", {}).get("snapshot_id"),
        "feature": lineage.get("feature", {}).get("snapshot_id"),
        "feature_payload_hash": lineage.get("feature", {}).get("payload_hash"),
        "cutoff": lineage.get("cutoff"),
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"gold-gap:{group}:{hashlib.sha256(encoded).hexdigest()[:20]}"


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
