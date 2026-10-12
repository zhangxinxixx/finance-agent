"""Transport contracts only; synthetic responses are not live source evidence."""
import json
from hashlib import sha256

import httpx

from apps.collectors.macro.fedwatch_free import PARENT_URL, collect_fedwatch_free


def test_http_failure_preserves_exact_body_hash_and_separate_events(tmp_path):
    body = b"synthetic denied response"
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403, content=body))) as client:
        first = collect_fedwatch_free(storage_root=tmp_path, client=client)
        second = collect_fedwatch_free(storage_root=tmp_path, client=client)
    assert first["parse_status"] == second["parse_status"] == "missing"
    assert first["snapshot_id"] != second["snapshot_id"]
    assert not first["rows"]
    manifest = json.loads((tmp_path / first["raw_artifact_ref"]).read_text())
    response = manifest["responses"][0]
    assert response["content_hash"] == sha256(body).hexdigest()
    assert (tmp_path / response["raw_artifact_ref"]).read_bytes() == body


def test_redirect_to_localhost_is_not_requested(tmp_path):
    urls = []
    def respond(request):
        urls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/secrets"})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = collect_fedwatch_free(storage_root=tmp_path, client=client)
    assert urls == [PARENT_URL]
    assert result["parse_status"] == "missing"
