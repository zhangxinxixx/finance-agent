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

__all__ = [
    "CONTEXT_BUNDLE_SCHEMA_VERSION",
    "LEGACY_CONTEXT_BUNDLE_SCHEMA_VERSION",
    "SCOPED_CONTEXT_BUNDLE_SCHEMA_VERSION",
    "AnalysisContextBundle",
    "ContextBlock",
    "ContextBundleBudgetExceeded",
    "EvidenceCursor",
    "EvidenceItem",
    "assemble_context_bundle",
    "select_incremental_evidence",
]
