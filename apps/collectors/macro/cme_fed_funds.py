"""Official settlement transport with immutable archive and bounded requests."""

import hashlib
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from curl_cffi import CurlOpt, requests

from apps.parsers.macro.cme_fed_funds import parse_settlements

SOURCE = "cme_settlement"
URL = "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/305/FUT"
MAX_BYTES = 4 * 1024 * 1024


class CMEFedFundsSettlementProvider:
    def __init__(self, *, session_factory=None):
        self.session_factory = session_factory or (
            lambda: requests.Session(impersonate="chrome", trust_env=False, curl_options={CurlOpt.PROXY: ""})
        )

    def collect(self, *, trade_date: date, storage_root: Path, now: datetime | None = None) -> dict:
        if isinstance(trade_date, datetime) or not isinstance(trade_date, date):
            raise ValueError("trade_date_required")
        clock = now or datetime.now(UTC)
        if clock.tzinfo is None:
            raise ValueError("timezone_required")
        identity = str(uuid4())
        root = Path(storage_root)
        folder = root / "raw/macro/cme_settlement" / clock.date().isoformat() / identity
        folder.mkdir(parents=True, exist_ok=False)
        body = bytearray()
        started = time.monotonic()
        record = {
            "schema_version": "cme_settlement_observation.v1",
            "source": SOURCE,
            "source_type": "official_market_data",
            "product_id": 305,
            "instrument": "FUT",
            "official_display_probability": False,
            "snapshot_id": identity,
            "trade_date": trade_date.isoformat(),
            "collector_version": "cme-settlement.v1.1-direct",
            "source_url": URL + "?tradeDate=" + trade_date.strftime("%m/%d/%Y"),
            "request_status": "failed",
            "data_status": "unavailable",
            "health": "unavailable",
            "http_status": None,
            "settlement_status": None,
            "rows": [],
            "warnings": [],
            "reason": None,
            "truncated": False,
        }
        try:
            with self.session_factory() as client:
                with client.stream("GET", record["source_url"], timeout=20, allow_redirects=False) as response:
                    record["http_status"] = response.status_code
                    record["content_type"] = response.headers.get("content-type")
                    for chunk in response.iter_content():
                        room = MAX_BYTES - len(body)
                        body.extend(chunk[:room])
                        if len(chunk) > room:
                            record["truncated"] = True
                            break
            code = record["http_status"]
            if code == 200:
                record["request_status"] = "success"
                if record["truncated"]:
                    record.update(health="parse_failed", data_status="parse_failed", reason="response_too_large")
                else:
                    try:
                        record.update(parse_settlements(bytes(body), trade_date=trade_date))
                        # Freshness is a read-time property, evaluated by the worker/query layer.
                        record["health"] = "available" if record["data_status"] == "available" else "upstream_empty"
                        if record["data_status"] == "upstream_empty" and trade_date.weekday() >= 5:
                            record.update(health="no_trade_day", data_status="no_trade_day")
                    except (ValueError, TypeError, KeyError, OverflowError):
                        record.update(
                            health="parse_failed", data_status="parse_failed", reason="invalid_settlement_payload"
                        )
            else:
                record.update(
                    health="blocked" if code in (401, 403, 429) else "unavailable", reason="upstream_http_" + str(code)
                )
        except requests.RequestsError as exc:
            record.update(
                reason="transport_" + type(exc).__name__,
                health="unavailable",
                transport_error_code=int(exc.code) if getattr(exc, "code", None) is not None else None,
            )
        record["latency_ms"] = round((time.monotonic() - started) * 1000)
        record["observed_at"] = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        record["bytes"] = len(body)
        record["content_hash"] = hashlib.sha256(body).hexdigest()
        raw_path = folder / "response.body"
        with raw_path.open("xb") as handle:
            handle.write(body)
        record["raw_artifact_ref"] = raw_path.relative_to(root).as_posix()
        record["manifest_ref"] = (folder / "manifest.json").relative_to(root).as_posix()
        record["source_refs"] = [
            {
                k: record[k]
                for k in (
                    "source",
                    "source_url",
                    "snapshot_id",
                    "trade_date",
                    "observed_at",
                    "content_hash",
                    "raw_artifact_ref",
                )
            }
        ]
        # Raw manifest contains collection diagnostics, never normalized contract rows.
        with (folder / "manifest.json").open("x") as handle:
            json.dump({k: v for k, v in record.items() if k != "rows"}, handle, indent=2, allow_nan=False)
        return record
