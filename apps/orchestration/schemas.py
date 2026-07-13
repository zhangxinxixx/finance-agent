from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TriggerType = Literal["hourly", "event_sla", "pre_analysis", "incident"]


@dataclass(frozen=True)
class OrchestrationArtifacts:
    run_id: str
    orchestration_plan_path: str
    notification_plan_path: str
    automation_summary_path: str
    workflow_runs_path: str
    retry_queue_path: str
    latest_pointer_path: str
    pre_analysis_gate_path: str | None = None

    def to_dict(self) -> dict[str, str]:
        artifacts = {
            "run_id": self.run_id,
            "orchestration_plan": self.orchestration_plan_path,
            "notification_plan": self.notification_plan_path,
            "automation_summary": self.automation_summary_path,
            "workflow_runs": self.workflow_runs_path,
            "retry_queue": self.retry_queue_path,
            "latest": self.latest_pointer_path,
        }
        if self.pre_analysis_gate_path:
            artifacts["pre_analysis_gate"] = self.pre_analysis_gate_path
        return artifacts
