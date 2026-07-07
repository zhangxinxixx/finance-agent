from __future__ import annotations

from typing import Any


def load_agent_registry() -> list[dict[str, Any]]:
    return [
        {
            "agent_name": "data_control_agent",
            "task_type": "data_control_agent",
            "capabilities": ["availability_calendar", "collection_plan", "processing_plan", "hourly_report"],
            "triggers": ["hourly"],
            "outputs": ["collection_plan", "processing_plan", "hourly_collection_processing_report"],
        },
        {
            "agent_name": "data_quality_monitor",
            "task_type": "data_quality_monitor",
            "capabilities": ["freshness", "completeness", "downstream_readiness"],
            "triggers": ["hourly", "event_sla", "pre_analysis", "incident"],
            "outputs": ["source_health", "data_quality_report", "downstream_readiness"],
        },
        {
            "agent_name": "event_sla_pipeline",
            "task_type": "event_sla_analysis",
            "capabilities": ["jin10_watcher", "cme_watcher", "sla_trace", "trading_strategy"],
            "triggers": ["event_sla"],
            "outputs": ["analysis_report", "trading_strategy", "sla_trace", "notification_request"],
        },
        {
            "agent_name": "feishu_notification_agent",
            "task_type": "feishu_notification",
            "capabilities": ["send_feishu", "record_delivery_result"],
            "triggers": ["hourly", "event_sla", "pre_analysis", "incident"],
            "outputs": ["notification_result"],
        },
    ]
