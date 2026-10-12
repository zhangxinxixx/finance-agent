import pytest
from apps.scheduler import task_wrapper


@pytest.mark.parametrize('outcome,terminal', [(None, 'success'), ({'status': 'skipped'}, 'skipped'), ({'status': 'unavailable'}, 'blocked'), ('raise', 'failed')])
def test_refresh_is_recorded_before_execution_and_failure_is_retained(monkeypatch, outcome, terminal):
    events = []

    class Recorder:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            events.append('run_started')
            return self
        def step(self, name, status, **kwargs):
            events.append(status)
            if status != 'running':
                assert kwargs['step_id'] == 'step-1'
            return 'step-1'
        def __exit__(self, kind, value, tb):
            events.append('run_failed' if kind else 'run_finished')

    def refresh():
        assert events == ['run_started', 'running']
        if outcome == 'raise':
            raise RuntimeError('source unavailable')
        return outcome

    monkeypatch.setattr(task_wrapper, 'TaskRecorder', Recorder)
    if outcome == 'raise':
        with pytest.raises(RuntimeError, match='source unavailable'):
            task_wrapper.record_jin10_refresh('news', 'news', refresh)
    else:
        assert task_wrapper.record_jin10_refresh('news', 'news', refresh) == outcome
    assert events[2] == terminal


def test_recording_failure_prevents_untracked_execution(monkeypatch):
    class Recorder:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            raise RuntimeError('database unavailable')
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(task_wrapper, 'TaskRecorder', Recorder)
    with pytest.raises(RuntimeError, match='database unavailable'):
        task_wrapper.record_jin10_refresh('news', 'news', lambda: pytest.fail('must not run'))
