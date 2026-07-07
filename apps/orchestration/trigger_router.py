from __future__ import annotations

from typing import Any


STEPS_BY_TRIGGER: dict[str, list[str]] = {
    "hourly": ["data_control_agent", "data_quality_monitor", "feishu_notification_agent"],
    "event_sla": ["event_sla_pipeline", "data_quality_monitor", "feishu_notification_agent"],
    "pre_analysis": ["data_quality_monitor", "feishu_notification_agent"],
    "incident": ["data_quality_monitor", "feishu_notification_agent"],
}


def resolve_trigger(*, trigger: str, registry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {item["agent_name"]: item for item in registry}
    steps = []
    for index, agent_name in enumerate(STEPS_BY_TRIGGER[trigger], start=1):
        agent = by_name[agent_name]
        steps.append(
            {
                "order": index,
                "agent_name": agent_name,
                "task_type": agent["task_type"],
                "capabilities": agent["capabilities"],
                "mode": "read_existing_artifacts" if agent_name != "feishu_notification_agent" else "dispatch_notification_plan",
            }
        )
    return steps
