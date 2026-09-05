from __future__ import annotations

from apps.runtime.source_controls import jin10_disabled


def test_jin10_disabled_defaults_to_false(monkeypatch) -> None:
    monkeypatch.delenv("FINANCE_AGENT_DISABLE_JIN10", raising=False)
    assert jin10_disabled() is False


def test_jin10_disabled_accepts_only_documented_true_values(monkeypatch) -> None:
    for value in ("1", "true", "yes", "on", " TRUE ", " YeS "):
        monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", value)
        assert jin10_disabled() is True

    for value in ("", "0", "false", "no", "off", "enabled", "1yes"):
        monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", value)
        assert jin10_disabled() is False
