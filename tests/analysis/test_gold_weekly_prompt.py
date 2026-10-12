"""Weekly method loading without changing research inputs or JSON contracts."""
from copy import deepcopy
import json

import pytest

from apps.analysis.agents import research_synthesis as synthesis
from apps.analysis.agents.research_input import encode


@pytest.mark.parametrize('version', ['gold_reader.v1', 'gold_reader.v2', 'gold_reader.v3', None, 'gold_reader.v5'])
def test_legacy_messages_do_not_depend_on_weekly_template(tmp_path, monkeypatch, version):
    monkeypatch.setattr(synthesis, '_WEEKLY_PROMPT_PATH', tmp_path / 'absent.md')
    payload = {'gold_workflow': {'reader_report_version': 'gold_reader.v4'},
               'observations': [{'value': 0, 'status': 'partial'}]}
    if version is not None:
        payload['report_profile'] = {'version': version}
    before = deepcopy(payload)

    messages = synthesis._build_messages(payload)

    assert messages == [
        {'role': 'system', 'content': synthesis._PROMPT_PATH.read_text(encoding='utf-8')},
        {'role': 'user', 'content': '只根据以下已校验输入输出 JSON；不要输出 Markdown 或代码围栏。\n' + encode(before)},
    ]
    assert payload == before


def test_v4_reads_current_file_and_preserves_final_input(tmp_path, monkeypatch):
    template = tmp_path / 'weekly.md'
    monkeypatch.setattr(synthesis, '_WEEKLY_PROMPT_PATH', template)
    payload = {'report_profile': {'version': 'gold_reader.v4'},
               'gold_workflow': {'state_record': {'accepted_state': None}},
               'observations': [{'value': 0, 'date': '2026-10-01'}]}
    before = deepcopy(payload)
    for content in ('独立临时方法参考 A', '独立临时修订方法参考 B'):
        template.write_text(content, encoding='utf-8')
        messages = synthesis._build_messages(payload)
        assert len(messages) == 3
        assert messages[0] == {'role': 'system', 'content': synthesis._PROMPT_PATH.read_text(encoding='utf-8')}
        assert messages[1]['role'] == 'user' and messages[1]['content'].endswith(content)
        assert messages[-1]['role'] == 'user'
        assert json.loads(messages[-1]['content'].split('\n', 1)[1]) == before
        assert payload == before


def test_missing_v4_method_is_not_silently_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(synthesis, '_WEEKLY_PROMPT_PATH', tmp_path / 'absent.md')
    payload = {'report_profile': {'version': 'gold_reader.v4'}}
    with pytest.raises(FileNotFoundError):
        synthesis._build_messages(payload)
    assert payload == {'report_profile': {'version': 'gold_reader.v4'}}


def test_actual_v4_gateway_receives_method_without_contract_or_state_changes():
    from tests.analysis.test_gold_detailed_report import snapshot, response
    from tests.analysis.test_research_synthesis import _output, _FakeGateway, _hard_fields

    data, original, answer = snapshot(), _output(), response()
    before_data = deepcopy(data)
    before_output = original.model_dump(mode='json')
    gateway = _FakeGateway(json.dumps(answer, ensure_ascii=False))

    result = synthesis.enrich_research_coordinator(data, original, gateway)

    assert len(gateway.calls) == 1
    call = gateway.calls[0]
    assert call['json_mode'] is True
    messages = call['messages']
    assert len(messages) == 3
    assert messages[1]['content'].endswith(synthesis._WEEKLY_PROMPT_PATH.read_text(encoding='utf-8'))
    assert json.loads(messages[-1]['content'].split('\n', 1)[1]) == call['audit_context']['input_payload']
    assert result.input_payload['research_synthesis']['status'] == 'success'
    assert result.input_payload['research_synthesis']['analysis'] == answer
    assert _hard_fields(result) == _hard_fields(original)
    assert data == before_data
    assert original.model_dump(mode='json') == before_output
