from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import httpx

from apps.notifications.feishu_card_builder import render_feishu_message
from apps.notifications.feishu_client import FeishuWebhookClient
from apps.notifications.schemas import NotificationRequest, NotificationResult
from apps.runtime.task_recorder import record_task

RecorderFactory = Callable[..., Any]


class FeishuNotificationAgent:
    def __init__(
        self,
        *,
        client: FeishuWebhookClient | None = None,
        recorder_factory: RecorderFactory | None = record_task,
        record_task_run: bool = True,
    ):
        self._client = client or FeishuWebhookClient.from_env()
        self._recorder_factory = recorder_factory
        self._record_task_run = record_task_run

    def send(self, request: NotificationRequest, *, http_client: httpx.Client | None = None) -> NotificationResult:
        title, message = render_feishu_message(request)
        if not self._record_task_run or self._recorder_factory is None:
            return self._client.send(request, rendered_title=title, rendered_message=message, client=http_client)

        try:
            with self._recorder_factory(
                task_type="feishu_notification",
                task_name=f"Feishu notification: {request.kind}",
                trade_date=request.trade_date,
            ) as recorder:
                result = self._client.send(request, rendered_title=title, rendered_message=message, client=http_client)
                step_status = _step_status(result)
                recorder.step(
                    "send_feishu",
                    status=step_status,
                    stage=request.kind,
                    task_kind="notification",
                    error=result.error,
                    source_refs=request.source_refs,
                    output_refs=[_result_output_ref(result)],
                )
                run_id = recorder.run_id() if hasattr(recorder, "run_id") else None
                result_with_run = replace(result, run_id=run_id)
                if result.status == "failed":
                    raise _NotificationFailed(result_with_run)
                return result_with_run
        except _NotificationFailed as exc:
            return exc.result

        raise RuntimeError("unreachable notification recorder state")


class _NotificationFailed(RuntimeError):
    def __init__(self, result: NotificationResult):
        super().__init__(result.error or "feishu notification failed")
        self.result = result


def _step_status(result: NotificationResult) -> str:
    if result.status == "disabled":
        return "skipped"
    if result.ok:
        return "success"
    return "failed"


def _result_output_ref(result: NotificationResult) -> dict[str, Any]:
    return {
        "artifact_type": "notification_result",
        "channel": "feishu",
        "status": result.status,
        "kind": result.kind,
        "title": result.title,
        "dry_run": result.dry_run,
        "status_code": result.status_code,
    }
