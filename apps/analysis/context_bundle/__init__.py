"""Provider-independent, immutable analysis context bundles."""

from .assembler import (
    ContextBundleBudgetExceeded,
    assemble_context_bundle,
    select_incremental_evidence,
)
from .schemas import (
    CONTEXT_BUNDLE_SCHEMA_VERSION,
    LEGACY_CONTEXT_BUNDLE_SCHEMA_VERSION,
    SCOPED_CONTEXT_BUNDLE_SCHEMA_VERSION,
    AnalysisContextBundle,
    ContextBlock,
    EvidenceCursor,
    EvidenceItem,
)
from .projection import (
    CONSUMER_PROJECTION_SCHEMA_VERSION,
    CONSUMER_EVIDENCE_TYPES,
    ConsumerProjection,
    bind_projection_to_agent_output,
    build_consumer_projection,
    consume_projection_for_agent_output,
    consumer_projection_payload,
    consumer_projection_summary,
    project_context_bundle,
    validate_consumer_projection,
)
from .snapshot_evidence import build_state_shadow_input, project_snapshot_evidence

__all__ = [
    "CONTEXT_BUNDLE_SCHEMA_VERSION",
    "CONSUMER_EVIDENCE_TYPES",
    "CONSUMER_PROJECTION_SCHEMA_VERSION",
    "LEGACY_CONTEXT_BUNDLE_SCHEMA_VERSION",
    "SCOPED_CONTEXT_BUNDLE_SCHEMA_VERSION",
    "AnalysisContextBundle",
    "ContextBlock",
    "ContextBundleBudgetExceeded",
    "ConsumerProjection",
    "EvidenceCursor",
    "EvidenceItem",
    "assemble_context_bundle",
    "bind_projection_to_agent_output",
    "build_state_shadow_input",
    "build_consumer_projection",
    "consume_projection_for_agent_output",
    "consumer_projection_payload",
    "consumer_projection_summary",
    "project_context_bundle",
    "project_snapshot_evidence",
    "select_incremental_evidence",
    "validate_consumer_projection",
]
