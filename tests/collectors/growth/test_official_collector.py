from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import httpx

from apps.collectors.growth.official import collect_growth_data
from apps.parsers.growth.official import (
    GDP_NOW_COMMENTARY_URL,
    GDP_NOW_SOURCE_URL,
    ISM_MANUFACTURING_SOURCE_URL_TEMPLATE,
    ISM_PRNEWSWIRE_ISSUER_URL,
    ISM_SERVICES_SOURCE_URL_TEMPLATE,
)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "macro" / "growth"
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def test_transient_connection_failure_retries_but_authentication_does_not():
    from apps.collectors.growth.official import _fetch
    from unittest.mock import Mock

    client = Mock()
    client.get.side_effect = [httpx.ConnectError("temporary"), _fixture_response("gdpnow_research_data.json")]
    result = _fetch(client, GDP_NOW_SOURCE_URL)
    assert result.failure_kind is None and result.attempts == 2
    client.get.side_effect = [_Response(403)]
    assert _fetch(client, GDP_NOW_SOURCE_URL).attempts == 1


class _Response:
    def __init__(self, status_code: int, body: bytes = b"", *, url: str | None = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.content = body
        self.url = url
        self.headers = headers or {}


class _Client:
    def __init__(self, responses: dict[str, _Response | Exception]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str) -> _Response:
        self.calls.append(url)
        response = self.responses.get(url)
        if isinstance(response, Exception):
            raise response
        if response is None:
            raise AssertionError(f"unexpected URL: {url}")
        return response


def _fixture_response(name: str, status_code: int = 200) -> _Response:
    return _Response(status_code, (FIXTURES / name).read_bytes())


def _success_client() -> _Client:
    current_mfg = ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="september")
    previous_mfg = ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="august")
    current_services = ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="september")
    previous_services = ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="august")
    return _Client({
        GDP_NOW_SOURCE_URL: _fixture_response("gdpnow_research_data.json"),
        GDP_NOW_COMMENTARY_URL: _fixture_response("gdpnow_commentary.html"),
        current_mfg: _Response(404, b"not published"),
        previous_mfg: _fixture_response("ism_manufacturing_august.html"),
        current_services: _Response(404, b"not published"),
        previous_services: _fixture_response("ism_services_august.html"),
    })


def test_growth_collector_archives_official_responses_and_health(tmp_path: Path) -> None:
    client = _success_client()

    result = collect_growth_data(
        retrieved_date="2026-09-08",
        storage_root=tmp_path,
        client=client,
        now=NOW,
    )

    assert [(point.symbol, point.date, point.value) for point in result.points] == [
        ("GDP_NOW", "2026-09-03", 4.7),
        ("ISM_MANUFACTURING", "2026-08-01", 54.6),
        ("ISM_SERVICES", "2026-08-01", 55.4),
        ("ISM_SERVICES_PRICES", "2026-08-01", 72.6),
    ]
    assert result.unavailable_symbols == []
    assert result.collector_health["gdp_now"]["collector_status"] == "success"
    assert result.collector_health["gdp_now"]["actual_latest_date"] == "2026-09-03"
    assert result.collector_health["gdp_now"]["official_latest_date"] == "2026-09-03"
    assert result.collector_health["gdp_now"]["expected_release_date"] == "2026-09-10"
    assert result.collector_health["gdp_now"]["expected_release_time"] is None
    assert result.collector_health["ism_manufacturing"]["candidate_status"] == "not_published"
    assert result.collector_health["ism_manufacturing"]["staleness"] == "fresh"
    assert result.collector_health["ism_manufacturing"]["expected_release_time"] == "2026-10-01T10:00:00-04:00"
    assert result.collector_health["ism_services"]["expected_release_time"] == "2026-10-05T10:00:00-04:00"
    assert result.collector_health["ism_services"]["expected_freshness"] == "monthly"
    assert all((tmp_path / point.raw_path).is_file() for point in result.points)
    assert (tmp_path / result.collector_health["gdp_now"]["commentary_raw_path"]).is_file()
    assert set(client.calls) == {
        GDP_NOW_SOURCE_URL,
        GDP_NOW_COMMENTARY_URL,
        ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="september"),
        ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="august"),
        ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="september"),
        ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="august"),
    }


def test_growth_collector_distinguishes_authentication_failure(tmp_path: Path) -> None:
    urls = {
        GDP_NOW_SOURCE_URL,
        ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="september"),
        ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="september"),
    }
    client = _Client({url: _Response(403, b"forbidden") for url in urls})

    result = collect_growth_data(
        retrieved_date="2026-09-08",
        storage_root=tmp_path,
        client=client,
        now=NOW,
    )

    assert set(result.unavailable_symbols) == {"GDP_NOW", "ISM_MANUFACTURING", "ISM_SERVICES", "ISM_SERVICES_PRICES"}
    assert result.collector_health["gdp_now"]["collector_status"] == "auth_failed"
    assert result.collector_health["ism_manufacturing"]["collector_status"] == "auth_failed"
    assert result.collector_health["ism_services"]["collector_status"] == "auth_failed"


def test_growth_collector_distinguishes_authentication_redirect_from_unpublished(tmp_path: Path) -> None:
    current_mfg = ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="september")
    current_services = ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="september")
    login_url = "https://ecommerce.ismworld.org/SSO/Login.aspx?token=redacted"
    client = _Client({
        GDP_NOW_SOURCE_URL: _fixture_response("gdpnow_research_data.json"),
        GDP_NOW_COMMENTARY_URL: _fixture_response("gdpnow_commentary.html"),
        current_mfg: _Response(200, b"<html>captcha</html>", url=login_url),
        current_services: _Response(302, b"redirect", headers={"location": login_url}),
    })

    result = collect_growth_data(
        retrieved_date="2026-09-08",
        storage_root=tmp_path,
        client=client,
        now=NOW,
    )

    assert result.collector_health["ism_manufacturing"]["collector_status"] == "auth_failed"
    assert result.collector_health["ism_services"]["collector_status"] == "auth_failed"
    assert result.collector_health["ism_services"]["reason"] == "official source redirected to authentication"
    assert result.collector_health["ism_services"]["release_status"] == "unavailable"
    assert all("token=" not in str(ref) for ref in result.source_refs)


def test_growth_collector_falls_back_when_candidate_page_is_published_shell_without_report(tmp_path: Path) -> None:
    current_mfg = ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="september")
    current_services = ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="september")
    previous_mfg = ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="august")
    previous_services = ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="august")
    client = _Client({
        GDP_NOW_SOURCE_URL: _fixture_response("gdpnow_research_data.json"),
        GDP_NOW_COMMENTARY_URL: _fixture_response("gdpnow_commentary.html"),
        current_mfg: _Response(404, b"not published"),
        previous_mfg: _fixture_response("ism_manufacturing_august.html"),
        current_services: _fixture_response("ism_services_current_unpublished.html"),
        previous_services: _fixture_response("ism_services_august.html"),
    })

    result = collect_growth_data(
        retrieved_date="2026-09-08",
        storage_root=tmp_path,
        client=client,
        now=NOW,
    )

    assert [(point.symbol, point.value) for point in result.points] == [
        ("GDP_NOW", 4.7),
        ("ISM_MANUFACTURING", 54.6),
        ("ISM_SERVICES", 55.4),
        ("ISM_SERVICES_PRICES", 72.6),
    ]
    assert result.collector_health["ism_services"]["candidate_status"] == "not_published"
    assert result.collector_health["ism_services"]["selected_period"] == "2026-08"


def test_growth_collector_distinguishes_fetch_failure(tmp_path: Path) -> None:
    urls = {
        GDP_NOW_SOURCE_URL,
        ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="september"),
        ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="september"),
    }
    client = _Client({url: RuntimeError("network unavailable") for url in urls})

    result = collect_growth_data(
        retrieved_date="2026-09-08",
        storage_root=tmp_path,
        client=client,
        now=NOW,
    )

    assert result.collector_health["gdp_now"]["collector_status"] == "fetch_failed"
    assert result.collector_health["ism_manufacturing"]["collector_status"] == "fetch_failed"
    assert result.collector_health["ism_services"]["collector_status"] == "fetch_failed"
    assert set(result.unavailable_symbols) == {"GDP_NOW", "ISM_MANUFACTURING", "ISM_SERVICES", "ISM_SERVICES_PRICES"}


def test_growth_collector_marks_unpublished_source_without_fabricating_value(tmp_path: Path) -> None:
    urls = {
        GDP_NOW_SOURCE_URL,
        ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="september"),
        ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="august"),
        ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="september"),
        ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="august"),
    }
    client = _Client({url: _Response(404, b"not published") for url in urls})

    result = collect_growth_data(
        retrieved_date="2026-09-08",
        storage_root=tmp_path,
        client=client,
        now=NOW,
    )

    assert result.points == []
    assert set(result.unavailable_symbols) == {"GDP_NOW", "ISM_MANUFACTURING", "ISM_SERVICES", "ISM_SERVICES_PRICES"}
    assert result.collector_health["gdp_now"]["collector_status"] == "not_published"
    assert result.collector_health["ism_manufacturing"]["collector_status"] == "not_published"
    assert result.collector_health["ism_services"]["staleness"] == "not_published"


def test_growth_collector_uses_issuer_prnewswire_when_ism_page_is_unavailable(tmp_path: Path) -> None:
    current_mfg = ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="september")
    previous_mfg = ISM_MANUFACTURING_SOURCE_URL_TEMPLATE.format(period="august")
    current_services = ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="september")
    previous_services = ISM_SERVICES_SOURCE_URL_TEMPLATE.format(period="august")
    article_url = "https://www.prnewswire.com/news-releases/manufacturing-pmi-at-54-6-august-2026-ism-manufacturing-pmi-report-302865127.html"
    client = _Client({
        GDP_NOW_SOURCE_URL: _fixture_response("gdpnow_research_data.json"),
        GDP_NOW_COMMENTARY_URL: _fixture_response("gdpnow_commentary.html"),
        # Current official page is blocked, while the prior official page is
        # also unavailable.  The issuer release is still public.
        current_mfg: _Response(403, b"SSO required"),
        previous_mfg: RuntimeError("ISM prior page unavailable"),
        ISM_PRNEWSWIRE_ISSUER_URL: _fixture_response("ism_prnewswire_index.html"),
        article_url: _fixture_response("ism_prnewswire_manufacturing_august.html"),
        current_services: _Response(404, b"not published"),
        previous_services: _fixture_response("ism_services_august.html"),
    })

    result = collect_growth_data(
        retrieved_date="2026-09-08",
        storage_root=tmp_path,
        client=client,
        now=NOW,
    )

    mfg = result.collector_health["ism_manufacturing"]
    assert [(point.symbol, point.value, point.source) for point in result.points] == [
        ("GDP_NOW", 4.7, "atlanta_fed_gdpnow"),
        ("ISM_MANUFACTURING", 54.6, "ism_prnewswire"),
        ("ISM_SERVICES", 55.4, "ism_official"),
        ("ISM_SERVICES_PRICES", 72.6, "ism_official"),
    ]
    assert result.unavailable_symbols == []
    assert mfg["source"] == "ism_prnewswire"
    assert mfg["fallback_used"] is True
    assert mfg["fallback_transport"] == "prnewswire"
    assert mfg["fallback_channel"] == "issuer_primary"
    assert mfg["issuer_verified"] is True
    assert mfg["official_source_status"] == "fetch_failed"
    assert mfg["release_date"] == "2026-09-01"
    assert mfg["release_time"] == "2026-09-01T10:00:00-04:00"
    assert (tmp_path / mfg["raw_path"]).is_file()
    assert (tmp_path / mfg["prnewswire_index_raw_path"]).is_file()
    mfg_ref = next(ref for ref in result.source_refs if ref["symbol"] == "ISM_MANUFACTURING")
    assert mfg_ref["source"] == "ism_prnewswire"
    assert mfg_ref["metadata"]["issuer_verified"] is True
