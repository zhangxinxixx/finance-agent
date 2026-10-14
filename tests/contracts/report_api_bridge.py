"""Explicit CI entry: isolated actual registry/TestClient -> actual Node consumer.

Run with ``python -m pytest tests/contracts/report_api_bridge.py --import-mode=importlib``.
Producer/consumer roots default to this checkout; overrides support uncommitted overlays.
No response DTO is constructed or repaired by this bridge.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
PRODUCER_SOURCES = (
    "apps/api/schemas/report.py",
    "apps/api/services/report_index_service.py",
    "apps/api/services/report_reading/detail.py",
    "apps/api/services/report_reading/gold_policy.py",
    "apps/worker/report_registry_sink.py",
    "tests/api/test_gold_policy_report_read_model_contract.py",
    "tests/api/test_gold_policy_report_delivery_api.py",
)


def fingerprint(root, sources):
    return {
        "head": subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(),
        "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources},
    }


def capture(producer, target):
    # Fresh interpreter and explicit sys.path prevent pytest's own checkout imports
    # from silently substituting the old public producer. cwd is temporary too.
    sys.path.insert(0, str(producer))
    import faulthandler
    import importlib.util

    faulthandler.dump_traceback_later(60)

    def deny_external(event, args):
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            name = Path(os.fsdecode(args[0])).name
            if name == ".env" or name.startswith(".env."):
                raise RuntimeError("Contract bridge forbids credential/environment file reads")
        if event in {"socket.connect", "socket.getaddrinfo", "socket.bind"}:
            raise RuntimeError(f"Contract bridge forbids real network: {event}")

    sys.addaudithook(deny_external)
    import pytest

    from tests.api import test_gold_policy_report_read_model_contract as fixture_module
    from tests.api.test_gold_policy_report_delivery_api import _client_with_session
    from database.models.analysis import AnalysisSnapshot
    from database.models.report import ReportArtifact, ReportItem
    from datetime import datetime, timezone

    # uvloop is already supplied by uvicorn[standard] on Linux. Its eventfd
    # wakeup works in restricted runners where asyncio's self-pipe can stall.
    # Ordinary CI without uvloop retains the standard TestClient backend.
    use_uvloop = importlib.util.find_spec("uvloop") is not None
    samples = []
    names = ("accepted", "observe", "degraded", "published", "archived", "unknown", "missing", "matching", "versions")
    for name in names:
        case_root = target / name
        case_root.mkdir()
        with pytest.MonkeyPatch.context() as patch:
            env = fixture_module.registered_gold.__wrapped__(case_root, patch)
            report_id = env["register"](name if name in {"observe", "degraded"} else "accepted", f"bridge-{name}")
            receipt = None
            with env["factory"]() as db:
                item = db.get(ReportItem, report_id)
                receipt = item.report_metadata["canonical_receipt_id"]
                if name in {"published", "archived"}:
                    item.lifecycle_status = name  # Explicit persisted fact, not a DTO modification.
                if name == "published":
                    item.report_metadata = {**item.report_metadata, "review_status": "approved"}
                elif name == "unknown":
                    item.report_metadata = {**item.report_metadata, "publication_status": "future-unknown"}
                elif name == "missing":
                    item.report_metadata = {}
                elif name == "matching":
                    payload = {
                        "snapshot_id": item.snapshot_id, "run_id": item.run_id,
                        "trade_date": item.trade_date.isoformat(), "snapshot_time": "2025-01-21T21:00:00Z",
                    }
                    raw = json.dumps(payload).encode()
                    artifact = case_root / "storage/features/contract-snapshot.json"
                    artifact.parent.mkdir(parents=True, exist_ok=True)
                    artifact.write_bytes(raw)
                    db.add(AnalysisSnapshot(
                        snapshot_id=item.snapshot_id, asset="XAUUSD", trade_date=item.trade_date,
                        run_id=item.run_id, payload=payload, payload_sha256=hashlib.sha256(raw).hexdigest(),
                        artifact_path=str(artifact),
                    ))
                db.commit()
            if name == "versions":
                first = report_id
                report_id = env["register"]("observe", "bridge-versions-second")
                with env["factory"]() as db:
                    receipt = db.get(ReportItem, report_id).report_metadata["canonical_receipt_id"]
                    for rid, minute in ((first, 1), (report_id, 2)):
                        for artifact in db.query(ReportArtifact).filter_by(report_id=rid):
                            artifact.generated_at = datetime(2025, 1, 21, 22, minute, tzinfo=timezone.utc)
                    db.commit()
            with env["factory"]() as db:
                client = _client_with_session(db)
                if use_uvloop:
                    client.async_backend["backend_options"]["use_uvloop"] = True
                urls = ["/api/reports/index", "/api/reports/dates", f"/api/reports/{report_id}"]
                urls += [f"/api/reports/{report_id}/{part}" for part in ("analysis", "source", "visual", "evidence")]
                responses = {}
                try:
                    for url in urls:
                        response = client.get(url)
                        assert response.status_code == 200, (name, url, response.status_code)
                        responses[url] = {"status": response.status_code, "body": response.json()}
                finally:
                    from apps.api.main import app

                    app.dependency_overrides.clear()
                    client.close()
            samples.append({"case": name, "report_id": report_id, "persisted_receipt": receipt, "responses": responses})
    origins = {}
    for name, module in list(sys.modules.items()):
        if name.startswith(("apps.", "database.", "tests.api.", "tests.analysis.")) and getattr(module, "__file__", None):
            path = Path(module.__file__).resolve()
            assert path.is_relative_to(producer), (name, path, producer)
            origins[name] = str(path.relative_to(producer))
    (target / "responses.json").write_text(json.dumps(samples, ensure_ascii=False) + "\n")
    (target / "producer.json").write_text(json.dumps({
        **fingerprint(producer, PRODUCER_SOURCES), "import_origins": origins,
        "testclient_backend": "asyncio+uvloop" if use_uvloop else "asyncio",
    }))
    faulthandler.cancel_dump_traceback_later()


def test_actual_report_api_frontend_bridge(tmp_path):
    producer = Path(os.environ.get("FINANCE_AGENT_CONTRACT_PRODUCER_ROOT", ROOT)).resolve()
    consumer = Path(os.environ.get("FINANCE_AGENT_CONTRACT_CONSUMER_ROOT", ROOT)).resolve()
    node = shutil.which("node")
    assert node, "Missing dependency: node must be installed on PATH"
    assert (producer / PRODUCER_SOURCES[-2]).is_file(), "Missing producer #130 registered_gold fixture"
    assert (consumer / "apps/frontend-web/scripts/strategy-test-harness.mjs").is_file(), "Missing consumer harness"
    evidence = tmp_path / "bridge"
    evidence.mkdir()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHON_DOTENV_DISABLED": "1",
           "DATABASE_URL": "sqlite:///:memory:", "no_proxy": "127.0.0.1,localhost,::1"}
    env.pop("FINANCE_AGENT_REPORT_CONTRACT_EVIDENCE", None)
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--capture", str(producer), str(evidence)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (evidence / "consumer.json").write_text(json.dumps(fingerprint(consumer, ())))
    result = subprocess.run(
        [node, str(ROOT / "apps/frontend-web/tests/check-report-api-bridge.mjs"), str(consumer), str(evidence)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((evidence / "receipt.json").read_text())
    assert receipt["passed"] and receipt["captured_response_count"] == 63
    if destination := os.environ.get("FINANCE_AGENT_CONTRACT_EVIDENCE_DIR"):
        # Never merge into or overwrite prior evidence, including producer checkout.
        destination = Path(destination).resolve()
        assert not destination.is_relative_to(producer) and not destination.is_relative_to(consumer)
        shutil.copytree(evidence, destination)
    print(result.stdout.strip())


if __name__ == "__main__":
    assert len(sys.argv) == 4 and sys.argv[1] == "--capture"
    capture(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve())
