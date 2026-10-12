"""Attach current mainstream evidence inside the existing snapshot merge step."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from apps.collectors.research.mainstream_news import collect_mainstream_news


def enrich_mainstream_news_snapshot(snapshot, *, storage_root, collector=collect_mainstream_news):
    result = deepcopy(snapshot)
    collected = collector(as_of=datetime.now(timezone.utc).isoformat(), storage_root=Path(storage_root))
    result['mainstream_news'] = collected
    result['source_refs'].extend(collected['source_refs'])
    result['input_snapshot_ids']['mainstream_news'] = collected['artifact_path']
    return result
