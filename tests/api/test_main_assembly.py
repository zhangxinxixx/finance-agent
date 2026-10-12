from apps.api import main
from apps.api.services import premarket_launch_service, premarket_task_service


def test_task_compatibility_exports_use_route_service_models_and_helpers():
    assert main.TaskCreateResponse is premarket_launch_service.TaskCreateResponse
    assert main.PremarketLaunchPreflightResponse is premarket_launch_service.PremarketLaunchPreflightResponse
    assert main.StepOut is premarket_task_service.StepOut
    assert main.TaskOut is premarket_task_service.TaskOut
    assert main._step_to_out is premarket_task_service.step_to_out
    assert main._try_parse_json is premarket_task_service._parse_json
