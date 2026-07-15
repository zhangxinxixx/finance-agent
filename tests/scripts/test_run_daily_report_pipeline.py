from __future__ import annotations

from scripts.run_daily_report_pipeline import daily_pipeline_exit_code


def test_daily_pipeline_exit_code_rejects_empty_daily_results() -> None:
    assert daily_pipeline_exit_code({"daily_reports": []}, requested_article_ids=["221250"]) == 2


def test_daily_pipeline_exit_code_rejects_missing_requested_article() -> None:
    summary = {
        "daily_reports": [
            {"run_id": "221251", "completion": {"completed": True, "status": "success"}},
        ]
    }

    assert daily_pipeline_exit_code(summary, requested_article_ids=["221250"]) == 2


def test_daily_pipeline_exit_code_accepts_success_and_limited_success() -> None:
    summary = {
        "daily_reports": [
            {"run_id": "221250", "completion": {"completed": True, "status": "success"}},
            {"run_id": "221251", "completion": {"completed": True, "status": "limited_success"}},
        ]
    }

    assert daily_pipeline_exit_code(summary, requested_article_ids=["221250", "221251"]) == 0


def test_daily_pipeline_exit_code_rejects_failed_completion() -> None:
    summary = {
        "daily_reports": [
            {"run_id": "221250", "completion": {"completed": False, "status": "failed"}},
        ]
    }

    assert daily_pipeline_exit_code(summary, requested_article_ids=["221250"]) == 2
