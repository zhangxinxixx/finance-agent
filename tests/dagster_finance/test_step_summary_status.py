from __future__ import annotations

from unittest.mock import patch

import pytest
from dagster import Failure, build_op_context

from apps.worker.pipelines.cme import CmePipelineState
from apps.worker.pipelines.macro import MacroPipelineState
from apps.worker.pipelines.news import NewsPipelineState
from dagster_finance.ops.cme import CmeConfig, cme_download_op
from dagster_finance.ops.macro import MacroConfig, macro_collect_op
from dagster_finance.ops.news import NewsConfig, news_collect_op


@pytest.mark.parametrize(
    ("target", "operation", "state", "config", "resources"),
    [
        (
            "dagster_finance.ops.macro.run_macro_step",
            macro_collect_op,
            MacroPipelineState(),
            MacroConfig(),
            {"db_session": object()},
        ),
        (
            "dagster_finance.ops.cme.run_cme_step",
            cme_download_op,
            CmePipelineState(),
            CmeConfig(),
            {"db_session": object()},
        ),
        (
            "dagster_finance.ops.news.run_news_step",
            news_collect_op,
            NewsPipelineState(),
            NewsConfig(),
            {"db_session": object()},
        ),
    ],
)
def test_pipeline_ops_fail_the_dagster_step_when_a_pipeline_summary_fails(
    target: str,
    operation,
    state,
    config,
    resources: dict[str, object],
) -> None:
    with patch(target, return_value={"status": "failed", "error": "collector unavailable"}):
        with pytest.raises(Failure, match="collector unavailable"):
            operation(build_op_context(resources=resources), state, config)
