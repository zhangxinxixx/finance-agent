"""Public official policy reference, separate from market-implied FedWatch."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import httpx

from apps.collectors.research.public_evidence import _read
from apps.parsers.macro.fed_target import parse_fed_target
from apps.runtime.immutable_artifact import immutable_json_item, write_immutable_artifact_bundle

SOURCE_URL = "https://www.federalreserve.gov/monetarypolicy/openmarket.htm"


def collect_fed_target(*, storage_root, client=None, now=None):
    if client is None:
        with httpx.Client(timeout=20, headers={"User-Agent": "finance-agent/0.1"}) as caller:
            return collect_fed_target(storage_root=storage_root, client=caller, now=now)
    now = now or datetime.now(UTC)
    identity = str(uuid4())
    root = Path(storage_root)
    raw_path = Path("raw/fed_policy_target") / (identity + ".json")
    result = {"status": "unavailable", "reference": None, "source_refs": []}
    raw = {"source_url": SOURCE_URL, "collected_at": now.isoformat(), "http_status": None}
    try:
        url, status, content = _read(client, SOURCE_URL)
        raw.update(source_url=url, http_status=status, body=content.decode("utf-8", errors="replace"),
                   content_hash=sha256(content).hexdigest())
        ref = {"source": "federal_reserve_target", "source_url": url, "retrieved_at": now.isoformat(),
               "raw_path": str(raw_path), "sha256": raw["content_hash"], "source_tier": "official_primary"}
        result["source_refs"] = [ref]
        if status == 200:
            result.update(status="available", reference=parse_fed_target(raw["body"], as_of=now.isoformat(), source_refs=[ref]))
        else:
            result["reason"] = "fed_target_http_" + str(status)
    except (httpx.HTTPError, ValueError) as exc:
        result["reason"] = str(exc) if isinstance(exc, ValueError) else "fed_target_transport_" + type(exc).__name__
    write_immutable_artifact_bundle([immutable_json_item(root / raw_path, raw)], storage_root=root)
    result["raw_artifact_ref"] = str(raw_path)
    return result
