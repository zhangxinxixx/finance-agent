"""Official-table fixtures with synthetic, rotating anonymous form state."""
import json

import pytest
from curl_cffi import requests

from apps.collectors.macro.fedwatch_webforms import collect_fedwatch_webforms, VIEW_URL
from apps.features.macro.fedwatch import build_fedwatch_health
from tests.collectors.test_fedwatch_browser import FIXTURE, NOW


def page(index, *, action=None):
    table = FIXTURE.read_text()
    if index == 1:
        table = table.replace("28 10月 2026", "9 12月 2026").replace("05:00:34", "05:00:36")
    action = action or f'./QuikStrikeView.aspx?viewitemid=IntegratedFedWatchTool&amp;qsid=test{index}'
    return (f'<form action="{action}"><input type="hidden" name="__VIEWSTATE" value="state{index}">'
            '<a id="ctrl0_lbMeeting" href="javascript:__doPostBack(\'ctrl0$lbMeeting\',\'\')">Oct</a>'
            '<a id="ctrl1_lbMeeting" href="javascript:__doPostBack(\'ctrl1$lbMeeting\',\'\')">Dec</a>'
            f'{table}</form>').encode()


class Response:
    def __init__(self, body, status=200, headers=None):
        self.body, self.status_code, self.headers = body, status, headers or {}
        self.closed = False

    def iter_content(self):
        yield self.body

    def close(self):
        self.closed = True


class Client:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        result = self.responses[len(self.calls) - 1]
        if isinstance(result, Exception):
            raise result
        return result


def test_archive_corruption_rejects_snapshot(tmp_path, monkeypatch):
    from pathlib import Path
    original = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda path: b'corrupt' if path.is_relative_to(tmp_path) else original(path))
    with pytest.raises(ValueError, match='fedwatch_raw_hash_mismatch'):
        collect_fedwatch_webforms(storage_root=tmp_path, now=NOW,
                                 client=Client([Response(page(0)), Response(page(0)), Response(page(1))]))


def test_session_redirect_postback_state_and_all_raw_are_preserved(tmp_path):
    responses = [Response(b'initial redirect', 302, {'Location': VIEW_URL + '&qsid=test0'}),
                 Response(page(0)), Response(page(0)), Response(page(1))]
    client = Client(responses)
    result = collect_fedwatch_webforms(storage_root=tmp_path, now=NOW, client=client)
    assert result['parse_status'] == 'ok'
    assert result['official_display_probability'] is True
    assert result['transport'] == 'curl_cffi_webforms'
    assert result['http_status'] == 200
    assert result['coverage']['captured_tab_count'] == 2
    assert result['coverage']['source_time_window']['span_seconds'] == 2
    assert build_fedwatch_health(result, as_of=NOW.isoformat())['status'] == 'fresh'
    quality = build_fedwatch_health(result, as_of=NOW.isoformat())['quality_summary']
    assert quality['raw_hash_verified'] is True
    assert quality['raw_response_count'] == 4
    assert quality['meeting_count'] == 2
    assert client.calls[2][0] == 'POST' and 'qsid=test0' in client.calls[2][1]
    assert client.calls[3][2]['data']['__EVENTTARGET'] == 'ctrl1$lbMeeting'
    assert client.calls[3][2]['data']['__VIEWSTATE'] == 'state0'
    assert all(r.closed for r in responses)
    manifest = json.loads((tmp_path / result['raw_artifact_ref']).read_text())
    assert len(manifest['responses']) == 4
    assert manifest['capture_kind'] == 'http_response'
    assert 'qsid' not in json.dumps(result['source_refs'])
    for raw, response in zip(manifest['responses'], responses):
        assert (tmp_path / raw['raw_artifact_ref']).read_bytes() == response.body
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database.models.fedwatch import ensure_fedwatch_tables
    from database.queries.fedwatch import save_fedwatch_snapshot, get_latest_fedwatch_snapshot
    with Session(create_engine('sqlite://')) as session:
        ensure_fedwatch_tables(session)
        save_fedwatch_snapshot(session, result)
        loaded = get_latest_fedwatch_snapshot(session, as_of=NOW.isoformat())
        assert loaded['transport'] == 'curl_cffi_webforms'
        assert build_fedwatch_health(loaded, as_of=NOW.isoformat())['status'] == 'fresh'
        assert build_fedwatch_health(loaded, as_of=NOW.isoformat())['quality_summary'] == quality


@pytest.mark.parametrize('redirect', [False, True])
def test_untrusted_redirect_or_form_is_not_requested(tmp_path, redirect):
    response = (Response(b'redirect', 302, {'Location': 'https://untrusted.example/form'}) if redirect
                else Response(page(0, action='https://untrusted.example/form')))
    client = Client([response])
    result = collect_fedwatch_webforms(storage_root=tmp_path, now=NOW, client=client)
    assert result['parse_status'] == 'missing'
    assert result['reason'] == 'official_http_untrusted_form_action'
    assert len(client.calls) == 1 and not result['rows']
    assert len(result['source_refs']) == 1


def test_duplicate_meeting_is_rejected_instead_of_false_coverage(tmp_path):
    client = Client([Response(page(0)), Response(page(0)), Response(page(0))])
    result = collect_fedwatch_webforms(storage_root=tmp_path, now=NOW, client=client)
    assert result['parse_status'] == 'parse_failed'
    assert result['reason'] == 'official_http_ValueError'


def test_later_transport_failure_keeps_partial_coverage_without_secret(tmp_path):
    client = Client([Response(page(0)), Response(page(0)),
                     requests.RequestsError('https://secret.example?token=private', code=35)])
    result = collect_fedwatch_webforms(storage_root=tmp_path, now=NOW, client=client)
    assert result['parse_status'] == 'ok'
    assert not result['coverage']['all_future_meetings']
    assert result['coverage']['captured_tab_count'] == 1
    assert 'private' not in json.dumps(result)


def test_http_block_page_is_archived_as_unavailable(tmp_path):
    client = Client([Response(b'access denied', 403)])
    result = collect_fedwatch_webforms(storage_root=tmp_path, now=NOW, client=client)
    assert result['parse_status'] == 'missing'
    assert result['reason'] == 'official_http_http_status_403'
    assert result['http_status'] == 403
    assert len(result['source_refs']) == 1


def test_public_anonymous_session_redirects_are_get_only(tmp_path):
    client = Client([
        Response(b'redirect', 302, {'Location': '/Account/Login.aspx?returnUrl=public'}),
        Response(b'redirect', 302, {'Location': VIEW_URL + '&qsid=test'}),
        Response(page(0)), Response(page(0)), Response(page(1)),
    ])
    result = collect_fedwatch_webforms(storage_root=tmp_path, now=NOW, client=client)
    assert result['parse_status'] == 'ok'
    assert client.calls[1][0] == 'GET' and 'data' not in client.calls[1][2]


def test_free_entry_uses_http_without_starting_browser_when_successful(monkeypatch, tmp_path):
    from apps.collectors.macro.fedwatch_free import collect_fedwatch_free
    value = {'parse_status': 'ok', 'transport': 'curl_cffi_webforms'}
    monkeypatch.setattr('apps.collectors.macro.fedwatch_webforms.collect_fedwatch_webforms', lambda **kw: value)
    def unexpected_browser():
        pytest.fail('HTTP success must not launch Chromium')
    monkeypatch.setattr('apps.collectors.macro.fedwatch_browser.browser_available', unexpected_browser)
    assert collect_fedwatch_free(storage_root=tmp_path) is value


def test_free_entry_retries_transport_once_then_preserves_failure(monkeypatch, tmp_path):
    from apps.collectors.macro.fedwatch_free import collect_fedwatch_free
    calls = []
    def failed(**kwargs):
        calls.append(kwargs)
        return {'parse_status': 'missing', 'reason': 'official_http_transport_curl_35'}
    monkeypatch.setattr('apps.collectors.macro.fedwatch_webforms.collect_fedwatch_webforms', failed)
    monkeypatch.setattr('apps.collectors.macro.fedwatch_browser.browser_available', lambda: False)
    assert collect_fedwatch_free(storage_root=tmp_path)['parse_status'] == 'missing'
    assert len(calls) == 2
    assert not calls[0].get('http1') and calls[1]['http1'] is True
