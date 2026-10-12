from unittest.mock import patch
import pytest
from apps.collectors.technical.collector import collect_technical, _collect_from_jin10_quote


@pytest.mark.parametrize("collector", [collect_technical, _collect_from_jin10_quote])
def test_retired_numeric_collector_is_unavailable_without_io(tmp_path, collector):
    with patch("apps.runtime.secret_resolver.resolve_runtime_secret") as secret, patch("httpx.Client") as network:
        result = collector(retrieved_date="2026-05-21", storage_root=tmp_path)
    secret.assert_not_called()
    network.assert_not_called()
    assert result.points == []
    assert result.unavailable_symbols == ["XAUUSD"]
    assert result.source_refs[0]["status"] == "unavailable"
    assert result.source_refs[0]["reason_code"] == "jin10_numeric_source_forbidden"
    assert list(tmp_path.iterdir()) == []
