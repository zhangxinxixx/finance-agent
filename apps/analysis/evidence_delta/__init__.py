"""Deterministic materiality decisions over state-scoped evidence deltas."""

from .evaluator import evaluate_evidence_delta
from .rules import adapt_context_evidence, adapt_figure_fact, semantic_hash, semantic_identity
from .schemas import (
    EVIDENCE_DELTA_RULESET_VERSION,
    EVIDENCE_DELTA_SCHEMA_VERSION,
    AffectedStateField,
    ConfirmationStatus,
    DeltaEvidence,
    EvidenceIdentity,
    EvaluatedEvidence,
    EvaluationOutcome,
    EvidenceDeltaDecision,
    FigureFactEvidence,
    KeyLevelEvidence,
    MacroMetricEvidence,
    MaterialEventEvidence,
    Materiality,
    OptionsRegimeEvidence,
    RecommendedAction,
    SourceQuality,
)

__all__ = [
    "EVIDENCE_DELTA_RULESET_VERSION",
    "EVIDENCE_DELTA_SCHEMA_VERSION",
    "AffectedStateField",
    "ConfirmationStatus",
    "DeltaEvidence",
    "EvidenceIdentity",
    "EvaluatedEvidence",
    "EvaluationOutcome",
    "EvidenceDeltaDecision",
    "FigureFactEvidence",
    "KeyLevelEvidence",
    "MacroMetricEvidence",
    "MaterialEventEvidence",
    "Materiality",
    "OptionsRegimeEvidence",
    "RecommendedAction",
    "SourceQuality",
    "adapt_context_evidence",
    "adapt_figure_fact",
    "evaluate_evidence_delta",
    "semantic_hash",
    "semantic_identity",
]
