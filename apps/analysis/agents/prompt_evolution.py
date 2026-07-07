from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


ROOT_CAUSES = {"prompt", "schema", "data_missing", "rule_gap", "frontend_binding", "dag", "unknown"}


@dataclass(frozen=True)
class FailurePattern:
    pattern_id: str
    description: str
    frequency: int
    examples: list[dict[str, Any]]
    likely_root_cause: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptUpdateProposal:
    proposal_id: str
    proposal_type: str
    before_summary: str
    after_summary: str
    patch: str
    rationale: str
    risk: str
    rollback_plan: str
    test_cases: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptEvolutionProposal:
    agent_name: str
    problem_summary: str
    failure_patterns: list[FailurePattern]
    prompt_update_proposal: PromptUpdateProposal
    requires_schema_change: bool
    requires_data_source_change: bool
    requires_dag_change: bool
    manual_review_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "problem_summary": self.problem_summary,
            "failure_patterns": [item.to_dict() for item in self.failure_patterns],
            "prompt_update_proposal": self.prompt_update_proposal.to_dict(),
            "requires_schema_change": self.requires_schema_change,
            "requires_data_source_change": self.requires_data_source_change,
            "requires_dag_change": self.requires_dag_change,
            "manual_review_required": self.manual_review_required,
        }


@dataclass(frozen=True)
class PromptEvaluationCase:
    case_id: str
    case_type: str
    input_payload: dict[str, Any]
    expected_assertions: list[str]
    failure_reason: str
    source_refs: list[Any]
    created_from: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptABCaseResult:
    case_id: str
    case_type: str
    status: str
    expected_assertions: list[str]
    active_failed_assertions: list[str]
    candidate_failed_assertions: list[str]
    improvement_assertions: list[str]
    regression_assertions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptABValidationResult:
    agent_name: str
    validation_status: str
    active_prompt_result: dict[str, Any]
    candidate_prompt_result: dict[str, Any]
    case_results: list[PromptABCaseResult]
    improvement_count: int
    regression_count: int
    risk_notes: list[str]
    proposal_only: bool = True
    activated_prompt: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "validation_status": self.validation_status,
            "active_prompt_result": self.active_prompt_result,
            "candidate_prompt_result": self.candidate_prompt_result,
            "case_results": [item.to_dict() for item in self.case_results],
            "improvement_count": self.improvement_count,
            "regression_count": self.regression_count,
            "risk_notes": self.risk_notes,
            "proposal_only": self.proposal_only,
            "activated_prompt": self.activated_prompt,
        }


def build_prompt_evaluation_cases(
    *,
    agent_name: str,
    failures: list[Any],
    created_from: str = "manual",
) -> list[PromptEvaluationCase]:
    cases: list[PromptEvaluationCase] = []
    for idx, failure in enumerate(failures):
        normalized = _normalize_finding(item=failure, example_ref=f"{created_from}:{idx}")
        pattern_id = str(normalized["pattern_id"] or f"failure:{idx}")
        case_type = _evaluation_case_type(pattern_id=pattern_id, description=str(normalized["description"]))
        source_refs = failure.get("source_refs") if isinstance(failure, dict) and isinstance(failure.get("source_refs"), list) else []
        cases.append(
            PromptEvaluationCase(
                case_id=f"{agent_name}:{case_type}:{pattern_id}",
                case_type=case_type,
                input_payload={
                    "agent_name": agent_name,
                    "failure_code": pattern_id,
                    "failure": failure,
                },
                expected_assertions=_expected_assertions(case_type=case_type),
                failure_reason=str(normalized["description"]),
                source_refs=list(source_refs),
                created_from=created_from,
            )
        )
    return cases


def run_prompt_ab_validation(
    *,
    agent_name: str,
    active_prompt_version: dict[str, Any],
    candidate_prompt_version: dict[str, Any],
    cases: list[PromptEvaluationCase],
    active_results: dict[str, dict[str, Any]],
    candidate_results: dict[str, dict[str, Any]],
) -> PromptABValidationResult:
    case_results = [
        _ab_case_result(
            case=case,
            active_result=active_results.get(case.case_id, {}),
            candidate_result=candidate_results.get(case.case_id, {}),
        )
        for case in cases
    ]
    improvement_count = sum(1 for item in case_results if item.improvement_assertions)
    regression_count = sum(1 for item in case_results if item.regression_assertions)
    candidate_failed_count = sum(1 for item in case_results if item.candidate_failed_assertions)
    validation_status = "pass" if regression_count == 0 and candidate_failed_count == 0 else "fail"
    return PromptABValidationResult(
        agent_name=agent_name,
        validation_status=validation_status,
        active_prompt_result={
            **active_prompt_version,
            "failed_case_count": sum(1 for item in case_results if item.active_failed_assertions),
        },
        candidate_prompt_result={
            **candidate_prompt_version,
            "failed_case_count": candidate_failed_count,
        },
        case_results=case_results,
        improvement_count=improvement_count,
        regression_count=regression_count,
        risk_notes=_ab_risk_notes(case_results),
    )


def build_prompt_evolution_proposal(
    *,
    agent_name: str,
    current_prompt: Any,
    recent_runs: list[dict[str, Any]],
    review_gate_findings: list[Any] | None = None,
    system_evolution_findings: list[Any] | None = None,
    manual_feedback: list[Any] | None = None,
    failed_test_cases: list[Any] | None = None,
    schema_version: str | None = None,
    data_source_health: dict[str, Any] | None = None,
    min_frequency: int = 2,
) -> PromptEvolutionProposal:
    evidence = _collect_evidence(
        recent_runs=recent_runs,
        review_gate_findings=review_gate_findings or [],
        system_evolution_findings=system_evolution_findings or [],
        manual_feedback=manual_feedback or [],
        failed_test_cases=failed_test_cases or [],
    )
    patterns = _aggregate_patterns(evidence=evidence)
    repeated = [item for item in patterns if item.frequency >= min_frequency]
    top_pattern = repeated[0] if repeated else (patterns[0] if patterns else _empty_pattern())
    requires_schema_change = any(item.likely_root_cause == "schema" for item in repeated)
    requires_data_source_change = any(item.likely_root_cause == "data_missing" for item in repeated)
    requires_dag_change = any(item.likely_root_cause == "dag" for item in repeated)
    proposal = _build_update_proposal(
        agent_name=agent_name,
        current_prompt=current_prompt,
        top_pattern=top_pattern,
        repeated_patterns=repeated,
        min_frequency=min_frequency,
        schema_version=schema_version,
        data_source_health=data_source_health or {},
    )
    if repeated:
        summary = f"Detected {len(repeated)} repeated failure pattern(s) for {agent_name}."
    elif patterns:
        summary = f"Only single-occurrence findings found for {agent_name}; prompt update is not justified yet."
    else:
        summary = f"No prompt quality failures found for {agent_name}."
    return PromptEvolutionProposal(
        agent_name=agent_name,
        problem_summary=summary,
        failure_patterns=patterns,
        prompt_update_proposal=proposal,
        requires_schema_change=requires_schema_change,
        requires_data_source_change=requires_data_source_change,
        requires_dag_change=requires_dag_change,
    )


def _collect_evidence(
    *,
    recent_runs: list[dict[str, Any]],
    review_gate_findings: list[Any],
    system_evolution_findings: list[Any],
    manual_feedback: list[Any],
    failed_test_cases: list[Any],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for idx, run in enumerate(recent_runs):
        if not isinstance(run, dict):
            continue
        example_ref = str(run.get("run_id") or run.get("agent_output_id") or f"recent_run:{idx}")
        for item in _finding_items(run):
            evidence.append(_normalize_finding(item=item, example_ref=example_ref))
        review_gate = run.get("review_gate")
        if isinstance(review_gate, dict):
            for item in _finding_items(review_gate):
                evidence.append(_normalize_finding(item=item, example_ref=example_ref))
    for source_name, findings in (
        ("review_gate", review_gate_findings),
        ("system_evolution", system_evolution_findings),
        ("manual_feedback", manual_feedback),
        ("failed_test_case", failed_test_cases),
    ):
        for idx, item in enumerate(findings):
            evidence.append(_normalize_finding(item=item, example_ref=f"{source_name}:{idx}"))
    return [item for item in evidence if item["description"]]


def _finding_items(payload: dict[str, Any]) -> list[Any]:
    items: list[Any] = []
    for key in (
        "failure_patterns",
        "quality_issues",
        "findings",
        "blocking_issues",
        "warnings",
        "manual_review_items",
        "failed_test_cases",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            items.extend(value)
    return items


def _normalize_finding(*, item: Any, example_ref: str) -> dict[str, Any]:
    if isinstance(item, dict):
        description = str(
            item.get("description")
            or item.get("message")
            or item.get("issue")
            or item.get("expected")
            or item.get("name")
            or ""
        )
        pattern_id = str(
            item.get("pattern_id")
            or item.get("issue_code")
            or item.get("code")
            or item.get("id")
            or _slug(description)
        )
        root_cause = _root_cause(item=item, description=description)
        example = {"ref": example_ref, "finding": item}
    else:
        description = str(item or "")
        pattern_id = _slug(description)
        root_cause = _root_cause(item={}, description=description)
        example = {"ref": example_ref, "finding": description}
    return {
        "pattern_id": pattern_id,
        "description": description,
        "likely_root_cause": root_cause,
        "example": example,
    }


def _aggregate_patterns(*, evidence: list[dict[str, Any]]) -> list[FailurePattern]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in evidence:
        pattern_id = item["pattern_id"] or _slug(item["description"])
        bucket = by_id.setdefault(
            pattern_id,
            {
                "pattern_id": pattern_id,
                "description": item["description"],
                "examples": [],
                "root_causes": [],
            },
        )
        bucket["examples"].append(item["example"])
        bucket["root_causes"].append(item["likely_root_cause"])
    patterns = [
        FailurePattern(
            pattern_id=str(bucket["pattern_id"]),
            description=str(bucket["description"]),
            frequency=len(bucket["examples"]),
            examples=list(bucket["examples"]),
            likely_root_cause=_dominant_root_cause(bucket["root_causes"]),
        )
        for bucket in by_id.values()
    ]
    return sorted(patterns, key=lambda item: (-item.frequency, item.pattern_id))


def _build_update_proposal(
    *,
    agent_name: str,
    current_prompt: Any,
    top_pattern: FailurePattern,
    repeated_patterns: list[FailurePattern],
    min_frequency: int,
    schema_version: str | None,
    data_source_health: dict[str, Any],
) -> PromptUpdateProposal:
    prompt_summary = _prompt_summary(current_prompt)
    test_cases = _test_cases(agent_name=agent_name, patterns=repeated_patterns or [top_pattern])
    if not repeated_patterns:
        return PromptUpdateProposal(
            proposal_id=f"no_prompt_change:{agent_name}",
            proposal_type="insufficient_evidence",
            before_summary=prompt_summary,
            after_summary="Keep the current prompt unchanged until the same failure repeats.",
            patch="",
            rationale=f"PromptEvolutionAgent requires at least {min_frequency} matching failures before proposing a prompt update.",
            risk="Changing a fixed prompt after a single observation can regress stable behavior.",
            rollback_plan="No production prompt change is proposed.",
            test_cases=test_cases,
        )
    if top_pattern.likely_root_cause == "data_missing":
        return PromptUpdateProposal(
            proposal_id=f"data_source_change:{agent_name}:{top_pattern.pattern_id}",
            proposal_type="data_source_change",
            before_summary=prompt_summary,
            after_summary="Keep the prompt unchanged; fix or explicitly gate missing data first.",
            patch="",
            rationale=f"Repeated failures are caused by data availability, not prompt wording. health={_health_summary(data_source_health)}",
            risk="Prompt changes could hide a source reliability problem.",
            rollback_plan="No prompt change; revert any downstream workaround and restore source health.",
            test_cases=test_cases,
        )
    if top_pattern.likely_root_cause == "schema":
        return PromptUpdateProposal(
            proposal_id=f"schema_update:{agent_name}:{top_pattern.pattern_id}",
            proposal_type="schema_update",
            before_summary=prompt_summary,
            after_summary=f"Review output schema {schema_version or 'unknown'} before changing prompt wording.",
            patch="",
            rationale="Repeated failures indicate the current schema cannot express the needed output.",
            risk="Prompt-only edits can produce fields that downstream consumers reject.",
            rollback_plan="Do not activate schema or prompt changes until schema tests pass.",
            test_cases=test_cases,
        )
    if top_pattern.likely_root_cause == "dag":
        return PromptUpdateProposal(
            proposal_id=f"dag_update:{agent_name}:{top_pattern.pattern_id}",
            proposal_type="dag_update",
            before_summary=prompt_summary,
            after_summary="Fix DAG/input wiring before changing prompt behavior.",
            patch="",
            rationale="Repeated failures point to missing upstream context or disconnected runtime nodes.",
            risk="Prompt changes cannot recover data that the Agent never receives.",
            rollback_plan="Revert DAG contract changes if trace tests fail.",
            test_cases=test_cases,
        )
    return PromptUpdateProposal(
        proposal_id=f"prompt_update:{agent_name}:{top_pattern.pattern_id}",
        proposal_type="prompt_update",
        before_summary=prompt_summary,
        after_summary=f"Add an explicit rule for repeated failure pattern: {top_pattern.description}",
        patch=_prompt_patch(pattern=top_pattern),
        rationale="The same prompt-quality failure appeared repeatedly and is not classified as data, schema, or DAG breakage.",
        risk="The new hard rule can over-constrain valid edge cases; requires ReviewGate and regression tests.",
        rollback_plan="Deactivate the proposed prompt version and restore the previous active prompt_version.",
        test_cases=test_cases,
    )


def _root_cause(*, item: dict[str, Any], description: str) -> str:
    explicit = str(
        item.get("likely_root_cause")
        or item.get("root_cause")
        or item.get("category")
        or item.get("cause")
        or ""
    ).strip().lower()
    if explicit in ROOT_CAUSES:
        return explicit
    text = f"{explicit} {description}".lower()
    if any(token in text for token in ("data_missing", "source missing", "p0 missing", "missing data", "数据缺失", "source_health")):
        return "data_missing"
    if any(token in text for token in ("schema", "output_schema", "field missing", "字段", "contract")):
        return "schema"
    if any(token in text for token in ("dag", "edge", "node", "trace path", "断链")):
        return "dag"
    if any(token in text for token in ("frontend", "dashboard", "page binding", "页面消费")):
        return "frontend_binding"
    if any(token in text for token in ("rule", "forbidden", "must", "必须", "缺规则")):
        return "rule_gap"
    if any(token in text for token in ("prompt", "source_refs", "mixed", "dominant_mainline", "one_line_conclusion", "overstated")):
        return "prompt"
    return "unknown"


def _dominant_root_cause(values: list[str]) -> str:
    counts = {value: values.count(value) for value in values}
    if not counts:
        return "unknown"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _evaluation_case_type(*, pattern_id: str, description: str) -> str:
    text = f"{pattern_id} {description}".lower()
    if "mixed" in text and ("decomposition" in text or "decompose" in text or "拆解" in text):
        return "mixed_decomposition"
    if "war" in text and "oil" in text and ("rate" in text or "real-rate" in text or "real_rate" in text):
        return "war_oil_rate_chain"
    if "source_refs" in text or "source refs" in text or "strong conclusion" in text:
        return "quality_gate"
    if "single source" in text or "单源" in text:
        return "mainline_attribution"
    if "render" in text or "report" in text:
        return "report_render"
    return "quality_gate"


def _expected_assertions(*, case_type: str) -> list[str]:
    assertions = ["no_direct_prompt_mutation", "must_not_bypass_quality_gate"]
    if case_type == "mixed_decomposition":
        assertions.append("mixed_must_be_decomposed")
    elif case_type == "war_oil_rate_chain":
        assertions.append("war_oil_rate_chain_required")
    elif case_type == "quality_gate":
        assertions.append("strong_conclusion_requires_source_refs")
    elif case_type == "mainline_attribution":
        assertions.append("single_source_must_not_be_fact")
    return assertions


def _ab_case_result(
    *,
    case: PromptEvaluationCase,
    active_result: dict[str, Any],
    candidate_result: dict[str, Any],
) -> PromptABCaseResult:
    expected = set(case.expected_assertions)
    active_failed = _failed_assertions(result=active_result, expected=expected)
    candidate_failed = _failed_assertions(result=candidate_result, expected=expected)
    improvement = sorted(active_failed - candidate_failed)
    regression = sorted(candidate_failed - active_failed)
    if regression:
        status = "regressed"
    elif improvement:
        status = "improved"
    elif candidate_failed:
        status = "unchanged_fail"
    else:
        status = "unchanged_pass"
    return PromptABCaseResult(
        case_id=case.case_id,
        case_type=case.case_type,
        status=status,
        expected_assertions=list(case.expected_assertions),
        active_failed_assertions=sorted(active_failed),
        candidate_failed_assertions=sorted(candidate_failed),
        improvement_assertions=improvement,
        regression_assertions=regression,
    )


def _failed_assertions(*, result: dict[str, Any], expected: set[str]) -> set[str]:
    explicit_failed = result.get("failed_assertions")
    if isinstance(explicit_failed, list):
        return {str(item) for item in explicit_failed if str(item) in expected}
    passed = result.get("passed_assertions")
    if isinstance(passed, list):
        return expected - {str(item) for item in passed}
    return set(expected)


def _ab_risk_notes(case_results: list[PromptABCaseResult]) -> list[str]:
    notes: list[str] = []
    regressions = [item.case_id for item in case_results if item.regression_assertions]
    if regressions:
        notes.append("candidate_has_regressions:" + ",".join(regressions[:5]))
    unresolved = [item.case_id for item in case_results if item.candidate_failed_assertions]
    if unresolved:
        notes.append("candidate_has_unresolved_failures:" + ",".join(unresolved[:5]))
    if not notes:
        notes.append("candidate_passed_all_prompt_evaluation_cases")
    return notes


def _prompt_patch(*, pattern: FailurePattern) -> str:
    return (
        f"Add a hard rule: when `{pattern.pattern_id}` is possible, the Agent must explicitly "
        "list evidence, missing data, source_refs, and a regression test case before emitting a strong conclusion."
    )


def _test_cases(*, agent_name: str, patterns: list[FailurePattern]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for pattern in patterns:
        cases.append(
            {
                "case_id": f"{agent_name}:{pattern.pattern_id}",
                "input": {
                    "agent_name": agent_name,
                    "failure_pattern": pattern.pattern_id,
                    "examples": pattern.examples[:2],
                },
                "expected": {
                    "likely_root_cause": pattern.likely_root_cause,
                    "manual_review_required": True,
                    "no_direct_prompt_mutation": True,
                },
            }
        )
    return cases


def _prompt_summary(current_prompt: Any) -> str:
    if isinstance(current_prompt, dict):
        agent_id = current_prompt.get("agent_id") or current_prompt.get("name") or "unknown"
        rules = current_prompt.get("rules") if isinstance(current_prompt.get("rules"), list) else []
        return f"agent={agent_id}; rules={len(rules)}"
    text = str(current_prompt or "")
    return text[:160]


def _health_summary(data_source_health: dict[str, Any]) -> str:
    if not data_source_health:
        return "unknown"
    return str(data_source_health.get("overall_status") or data_source_health.get("status") or "unknown")


def _empty_pattern() -> FailurePattern:
    return FailurePattern(
        pattern_id="no_failure_observed",
        description="No failure observed.",
        frequency=0,
        examples=[],
        likely_root_cause="unknown",
    )


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned[:80] or "unknown_failure"
