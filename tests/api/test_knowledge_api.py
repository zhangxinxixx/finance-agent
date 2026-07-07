from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_api_knowledge_items_returns_unavailable_contract() -> None:
    response = client.get("/api/knowledge/items")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["source"] == "unavailable"
    assert payload["items"] == []
    assert payload["stats"]["total"] == 0


def test_api_knowledge_item_missing_returns_404() -> None:
    response = client.get("/api/knowledge/items/missing-item")

    assert response.status_code == 404
    assert response.json()["detail"] == "Knowledge item not found"


def test_api_knowledge_items_reads_storage_read_model(tmp_path, monkeypatch) -> None:
    path = tmp_path / "items.json"
    path.write_text(
        json.dumps(
            {
                "status": "available",
                "source": "storage_read_model",
                "updated_at": "2026-07-08T00:00:00+00:00",
                "items": [
                    {
                        "id": "jin10-master-review-2026-07-07-223556",
                        "title": "大师复盘候选",
                        "type": "review",
                        "typeLabel": "复盘",
                        "topic": "黄金",
                        "status": "待复核",
                        "summary": "候选知识。",
                        "thesis": "需要人工复核。",
                        "updated": "2026-07-07",
                        "createdAt": "2026-07-08T00:00:00+00:00",
                        "verifiedAt": "",
                        "version": "candidate-v1",
                        "author": "jin10_report_analysis_agent",
                        "confidence": 52,
                        "citations": 1,
                        "references": 1,
                        "dashboards": 0,
                        "agentReady": False,
                        "playbookReady": False,
                        "pinned": False,
                        "reviewQueued": True,
                        "tags": ["Jin10", "大师复盘"],
                        "scenes": [],
                        "rules": [],
                        "inputs": [],
                        "monitorMetrics": [],
                        "evidence": [],
                        "downstream": [],
                        "timeline": [],
                        "citationFlow": {"upstream": [], "downstream": []},
                    }
                ],
                "source_refs": [{"source": "jin10_agent_analysis_report"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FINANCE_AGENT_KNOWLEDGE_ITEMS_PATH", str(path))

    response = client.get("/api/knowledge/items")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available"
    assert payload["source"] == "storage_read_model"
    assert payload["items"][0]["id"] == "jin10-master-review-2026-07-07-223556"
    assert payload["stats"]["total"] == 1
    assert payload["stats"]["review_queue_count"] == 1
    assert payload["source_refs"][0]["source"] == "jin10_agent_analysis_report"


def test_api_knowledge_item_reads_storage_detail(tmp_path, monkeypatch) -> None:
    path = tmp_path / "items.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "candidate-1",
                        "title": "大师复盘候选",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FINANCE_AGENT_KNOWLEDGE_ITEMS_PATH", str(path))

    response = client.get("/api/knowledge/items/candidate-1")

    assert response.status_code == 200
    assert response.json()["title"] == "大师复盘候选"
