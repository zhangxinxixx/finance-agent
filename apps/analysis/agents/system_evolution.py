from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SystemEvolutionFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str = ""
    code: str
    severity: str
    category: str = ""
    title: str = ""
    message: str
    description: str = ""
    affected_entities: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    created_at: str = "1970-01-01T00:00:00+00:00"

    @model_validator(mode="after")
    def fill_issue_contract_fields(self) -> "SystemEvolutionFinding":
        if not self.finding_id:
            self.finding_id = f"finding:{self.code}"
        if not self.category:
            self.category = _finding_category(self.code)
        if not self.title:
            self.title = self.code.replace("_", " ")
        if not self.description:
            self.description = self.message
        if not self.affected_entities:
            self.affected_entities = _affected_entities(self.code, self.evidence)
        return self


class ImprovementProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    proposal_type: str = "backend_rule_update"
    title: str = ""
    rationale: str
    proposed_changes: list[str]
    expected_impact: str
    risks: list[str]
    rollback_plan: str
    test_plan: list[str]
    status: str = "pending_review"
    finding_codes: list[str]

    @model_validator(mode="after")
    def fill_issue_contract_fields(self) -> "ImprovementProposal":
        if not self.title:
            self.title = self.proposal_id.removeprefix("proposal:").replace("_", " ")
        return self


class SystemEvolutionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = "system_evolution_agent"
    review_status: str
    blocked: bool
    findings: list[SystemEvolutionFinding]
    evolution_proposals: list[ImprovementProposal]
    required_followups: list[str]
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


def evaluate_system_evolution(
    *,
    gold_macro_overview: dict[str, Any] | None = None,
    source_health: dict[str, Any] | None = None,
    dashboard_summary: dict[str, Any] | None = None,
    quality_gate_decision: dict[str, Any] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
) -> SystemEvolutionReview:
    """Build a deterministic governance review for Gold v3 closeout checks.

    This is intentionally read-only. It does not mutate runtime artifacts or
    prompts; it only converts known contract risks into auditable findings and
    proposals for SystemEvolutionAgent.
    """

    overview = dict(gold_macro_overview or {})
    health = dict(source_health or overview.get("source_health") or {})
    dashboard = dict(dashboard_summary or {})
    quality_gate = dict(quality_gate_decision or overview.get("review_gate") or {})

    findings: list[SystemEvolutionFinding] = []

    if _mixed_without_driver_decomposition(overview):
        findings.append(
            SystemEvolutionFinding(
                code="mixed_without_driver_decomposition",
                severity="critical",
                message="Mixed GoldMacroOverview output is missing bullish/bearish driver decomposition.",
                evidence={"net_bias": overview.get("net_bias"), "driver_conflict": overview.get("driver_conflict")},
            )
        )

    if _needs_war_oil_rate_chain(overview) and not isinstance(overview.get("war_oil_rate_chain"), dict):
        findings.append(
            SystemEvolutionFinding(
                code="war_oil_rate_chain_missing",
                severity="high",
                message="Geopolitical or oil-sensitive overview is missing war_oil_rate_chain.",
                evidence={"dominant_mainline": overview.get("dominant_mainline"), "net_bias": overview.get("net_bias")},
            )
        )

    if _dashboard_strong_conclusion_without_refs(dashboard):
        findings.append(
            SystemEvolutionFinding(
                code="dashboard_strong_conclusion_without_source_refs",
                severity="critical",
                message="Dashboard exposes a strong conclusion without source_refs.",
                evidence={"one_line_conclusion": dashboard.get("one_line_conclusion") or dashboard.get("headline")},
            )
        )

    if _p0_gap_with_strong_conclusion(overview=overview, health=health):
        findings.append(
            SystemEvolutionFinding(
                code="p0_gap_strong_conclusion",
                severity="critical",
                message="P0 source gaps conflict with a strong GoldMacroOverview conclusion.",
                evidence={"p0_missing": list(health.get("p0_missing") or []), "net_bias": overview.get("net_bias")},
            )
        )

    for finding in _quality_gate_findings(quality_gate):
        findings.append(finding)

    findings = _dedupe_findings(findings)
    blocked = any(item.severity in {"critical", "blocker"} for item in findings)
    review_status = "blocked" if blocked else ("needs_change" if findings else "pass")

    return SystemEvolutionReview(
        review_status=review_status,
        blocked=blocked,
        findings=findings,
        evolution_proposals=_build_proposals(findings),
        required_followups=[item.code for item in findings],
        source_refs=_merge_source_refs([source_refs or [], overview.get("source_refs") or [], dashboard.get("source_refs") or []]),
    )


def _mixed_without_driver_decomposition(overview: dict[str, Any]) -> bool:
    if str(overview.get("net_bias") or "").lower() not in {"mixed", "mixed_bullish", "mixed_bearish"}:
        return False
    conflict = overview.get("driver_conflict")
    if not isinstance(conflict, dict):
        return True
    bullish = conflict.get("bullish_drivers")
    bearish = conflict.get("bearish_drivers")
    dominant = conflict.get("dominant_driver")
    verification = conflict.get("verification_needed")
    return not (
        isinstance(bullish, list)
        and bool(bullish)
        and isinstance(bearish, list)
        and bool(bearish)
        and bool(dominant)
        and isinstance(verification, list)
        and bool(verification)
    )


def _needs_war_oil_rate_chain(overview: dict[str, Any]) -> bool:
    sensitive_mainlines = {"geopolitical_war_risk", "oil_prices", "real_rates_usd"}
    if str(overview.get("dominant_mainline") or "") in sensitive_mainlines:
        return True
    for row in overview.get("theme_rankings") or []:
        if not isinstance(row, dict):
            continue
        if row.get("mainline_id") in sensitive_mainlines and row.get("coverage_status") == "covered":
            return True
    return False


def _dashboard_strong_conclusion_without_refs(dashboard: dict[str, Any]) -> bool:
    if not dashboard:
        return False
    refs = dashboard.get("source_refs") or dashboard.get("event_ids") or []
    if refs:
        return False
    text = " ".join(str(dashboard.get(key) or "") for key in ("one_line_conclusion", "headline", "net_bias", "phase")).lower()
    return _contains_strong_conclusion(text)


def _p0_gap_with_strong_conclusion(*, overview: dict[str, Any], health: dict[str, Any]) -> bool:
    if not health.get("p0_missing") and health.get("can_build_gold_macro_overview") is not False:
        return False
    text = " ".join(
        str(overview.get(key) or "") for key in ("phase", "net_bias", "one_line_conclusion", "priority_regime")
    ).lower()
    return _contains_strong_conclusion(text)


def _contains_strong_conclusion(text: str) -> bool:
    return any(term in text for term in ("strong", "breakout", "high_conviction", "strong_bullish", "strong_bearish"))


def _quality_gate_findings(quality_gate: dict[str, Any]) -> list[SystemEvolutionFinding]:
    if not quality_gate:
        return []
    findings: list[SystemEvolutionFinding] = []
    if quality_gate.get("publish_allowed") is False or quality_gate.get("review_status") == "blocked":
        findings.append(
            SystemEvolutionFinding(
                code="quality_gate_blocked",
                severity="critical",
                message="ReviewGate blocked publication.",
                evidence={"action": quality_gate.get("action"), "review_status": quality_gate.get("review_status")},
            )
        )
    for item in quality_gate.get("findings") or []:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "medium")
        findings.append(
            SystemEvolutionFinding(
                code=str(item.get("code") or "quality_gate_finding"),
                severity="critical" if severity == "blocker" else severity,
                message=str(item.get("message") or "Quality gate finding."),
                evidence=dict(item.get("evidence") or {}),
            )
        )
    return findings


def _build_proposals(findings: list[SystemEvolutionFinding]) -> list[ImprovementProposal]:
    proposals: list[ImprovementProposal] = []
    for finding in findings:
        proposals.append(
            ImprovementProposal(
                proposal_id=f"proposal:{finding.code}",
                rationale=finding.message,
                proposed_changes=_proposal_changes(finding.code),
                expected_impact="Reduce silent publication risk and make the next Gold v3 run auditable.",
                risks=["May increase manual review volume until source coverage improves."],
                rollback_plan="Disable this proposal and keep the current read-only artifacts unchanged.",
                test_plan=[
                    "Run targeted SystemEvolutionAgent contract tests.",
                    "Run QualityGate and GoldMacroOverview regression tests for the affected path.",
                ],
                finding_codes=[finding.code],
            )
        )
    return proposals


def _finding_category(code: str) -> str:
    if code == "mixed_without_driver_decomposition":
        return "driver_decomposition"
    if code == "war_oil_rate_chain_missing":
        return "transmission_chain"
    if code == "dashboard_strong_conclusion_without_source_refs":
        return "view_binding"
    if code == "p0_gap_strong_conclusion":
        return "data_source_gap"
    if code in {"quality_gate_blocked", "source_refs_missing"}:
        return "report_quality"
    return "runtime_quality"


def _affected_entities(code: str, evidence: dict[str, Any]) -> dict[str, Any]:
    entities: dict[str, Any] = {"finding_codes": [code]}
    for key in ("event_ids", "input_ids", "source_refs", "page_slots", "dag_node_ids", "agent_names"):
        value = evidence.get(key)
        if isinstance(value, list) and value:
            entities[key] = value
    return entities


def _proposal_changes(code: str) -> list[str]:
    if code == "mixed_without_driver_decomposition":
        return ["Require driver_conflict bullish_drivers, bearish_drivers, dominant_driver, and verification_needed before publication."]
    if code == "war_oil_rate_chain_missing":
        return ["Block geopolitical/oil-sensitive overviews until war_oil_rate_chain is generated or explicitly degraded."]
    if code == "dashboard_strong_conclusion_without_source_refs":
        return ["Require Dashboard strong conclusions to carry source_refs or event_ids from GoldMacroOverview."]
    if code == "p0_gap_strong_conclusion":
        return ["Downgrade strong conclusions to observe/wait when P0 source health is missing."]
    return ["Route the finding through ReviewGate and add a regression test for the failing contract."]


def _dedupe_findings(findings: list[SystemEvolutionFinding]) -> list[SystemEvolutionFinding]:
    result: list[SystemEvolutionFinding] = []
    seen: set[str] = set()
    for finding in findings:
        if finding.code in seen:
            continue
        seen.add(finding.code)
        result.append(finding)
    return result


def _merge_source_refs(groups: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            key = repr(sorted(item.items()))
            if key in seen:
                continue
            seen.add(key)
            result.append(dict(item))
    return result
