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
