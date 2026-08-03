from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_STACK_SCRIPT = PROJECT_ROOT / "scripts" / "local_stack_ctl.sh"


@contextmanager
def _fake_health_api(*, refresh_enabled: str, refresh_jobs: str):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server_code = """
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *args):
        return

HTTPServer(("127.0.0.1", int(os.environ["TEST_API_PORT"])), Handler).serve_forever()
"""
    server_env = {
        **os.environ,
        "TEST_API_PORT": str(port),
        "FINANCE_AGENT_ENABLE_API_BACKGROUND_REFRESH": refresh_enabled,
        "FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS": refresh_jobs,
    }
    process = subprocess.Popen(
        [sys.executable, "-c", server_code],
        cwd=PROJECT_ROOT,
        env=server_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        health_url = f"http://127.0.0.1:{port}/health"
        for _ in range(50):
            try:
                with urllib.request.urlopen(health_url, timeout=0.2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("fake health API did not start")
        yield process, port
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_local_stack_enables_required_market_background_refresh_by_default() -> None:
    script = (PROJECT_ROOT / "scripts" / "local_stack_ctl.sh").read_text(encoding="utf-8")

    assert (
        'export FINANCE_AGENT_ENABLE_API_BACKGROUND_REFRESH="${FINANCE_AGENT_ENABLE_API_BACKGROUND_REFRESH:-1}"'
        in script
    )
    assert (
        'export FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS="${FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS:-jin10_kline,twelvedata_xauusd_dispatch,market_candles_daily}"'
        in script
    )


def test_local_stack_keeps_explicit_background_refresh_override() -> None:
    script = (PROJECT_ROOT / "scripts" / "local_stack_ctl.sh").read_text(encoding="utf-8")

    assert 'FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS:-jin10_kline,twelvedata_xauusd_dispatch,market_candles_daily' in script


def test_local_stack_adopts_api_with_required_background_refresh_jobs(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    with _fake_health_api(
        refresh_enabled="1",
        refresh_jobs="jin10_kline,twelvedata_xauusd_dispatch,market_candles_daily",
    ) as (process, port):
        result = subprocess.run(
            ["bash", str(LOCAL_STACK_SCRIPT), "status", "--frontend=none"],
            cwd=PROJECT_ROOT,
            env={
                **os.environ,
                "FINANCE_AGENT_STATE_DIR": str(state_dir),
                "FINANCE_AGENT_API_PORT": str(port),
                "FINANCE_AGENT_FRONTEND_PORT": str(port + 1),
            },
            check=True,
            capture_output=True,
            text=True,
        )

    assert (state_dir / "api.pid").read_text(encoding="utf-8").strip() == str(process.pid)
    assert "refresh misconfigured" not in result.stdout


@pytest.mark.parametrize(
    ("refresh_enabled", "refresh_jobs"),
    [
        ("0", "jin10_kline,twelvedata_xauusd_dispatch,market_candles_daily"),
        ("1", "jin10_kline"),
        ("1", "twelvedata_xauusd_dispatch"),
        ("1", "jin10_kline,twelvedata_xauusd_dispatch"),
    ],
)
def test_local_stack_refuses_to_adopt_api_without_required_background_refresh(
    tmp_path: Path,
    refresh_enabled: str,
    refresh_jobs: str,
) -> None:
    state_dir = tmp_path / "state"
    with _fake_health_api(refresh_enabled=refresh_enabled, refresh_jobs=refresh_jobs) as (_process, port):
        result = subprocess.run(
            ["bash", str(LOCAL_STACK_SCRIPT), "status", "--frontend=none"],
            cwd=PROJECT_ROOT,
            env={
                **os.environ,
                "FINANCE_AGENT_STATE_DIR": str(state_dir),
                "FINANCE_AGENT_API_PORT": str(port),
                "FINANCE_AGENT_FRONTEND_PORT": str(port + 1),
            },
            check=True,
            capture_output=True,
            text=True,
        )

    assert not (state_dir / "api.pid").exists()
    assert "Refusing to adopt API" in result.stderr
    assert "API status:        running, refresh misconfigured" in result.stdout


def test_local_stack_revalidates_existing_api_pidfile_without_killing_process(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    with _fake_health_api(
        refresh_enabled="1",
        refresh_jobs="jin10_kline",
    ) as (process, port):
        (state_dir / "api.pid").write_text(f"{process.pid}\n", encoding="utf-8")
        result = subprocess.run(
            ["bash", str(LOCAL_STACK_SCRIPT), "status", "--frontend=none"],
            cwd=PROJECT_ROOT,
            env={
                **os.environ,
                "FINANCE_AGENT_STATE_DIR": str(state_dir),
                "FINANCE_AGENT_API_PORT": str(port),
                "FINANCE_AGENT_FRONTEND_PORT": str(port + 1),
            },
            check=True,
            capture_output=True,
            text=True,
        )

        assert process.poll() is None
        assert not (state_dir / "api.pid").exists()

    assert "Refusing managed API" in result.stderr
    assert "API status:        running, refresh misconfigured" in result.stdout


def test_local_stack_manages_dagster_daemon_with_shared_runtime_environment() -> None:
    script = (PROJECT_ROOT / "scripts" / "local_stack_ctl.sh").read_text(encoding="utf-8")

    assert 'DAGSTER_HOME_PATH="${DAGSTER_HOME:-$STATE_DIR/dagster-home}"' in script
    assert 'export DATABASE_URL="${DATABASE_URL:-$DATABASE_URL_DEFAULT}"' in script
    assert 'export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"' in script
    assert "export no_proxy=127.0.0.1,localhost,::1" in script
    assert "setsid .venv/bin/dagster-daemon run -w workspace.yaml" in script
    assert ".venv/bin/dagster-daemon liveness-check" in script
    assert ".venv/bin/dagster instance info" in script


def test_local_stack_manages_dagster_webserver_and_graphql_with_shared_runtime_environment() -> None:
    script = (PROJECT_ROOT / "scripts" / "local_stack_ctl.sh").read_text(encoding="utf-8")

    assert 'DAGSTER_WEB_PORT="${FINANCE_AGENT_DAGSTER_WEB_PORT:-3333}"' in script
    assert 'DAGSTER_GRAPHQL_URL_DEFAULT="${DAGSTER_WEB_URL}/graphql"' in script
    assert 'export DAGSTER_GRAPHQL_URL="${DAGSTER_GRAPHQL_URL:-$DAGSTER_GRAPHQL_URL_DEFAULT}"' in script
    assert "setsid .venv/bin/dagster-webserver -w workspace.yaml -h 127.0.0.1" in script
    assert "start_dagster_webserver" in script
    assert "stop_dagster_webserver" in script
    assert "dagster_graphql_check" in script


def test_local_stack_initializes_dagster_instance_before_starting_daemon() -> None:
    script = (PROJECT_ROOT / "scripts" / "local_stack_ctl.sh").read_text(encoding="utf-8")
    function_start = script.index("start_dagster_daemon()")
    function_end = script.index("\n}\n", function_start)
    function = script[function_start:function_end]

    assert function.index("initialize_dagster_instance") < function.index(
        "setsid .venv/bin/dagster-daemon run -w workspace.yaml"
    )
    assert "Dagster instance initialization failed." in function


def test_local_stack_dagster_identity_guard_precedes_stop() -> None:
    script = (PROJECT_ROOT / "scripts" / "local_stack_ctl.sh").read_text(encoding="utf-8")

    function_start = script.index("stop_dagster_daemon()")
    function_end = script.index("\n}\n", function_start)
    function = script[function_start:function_end]
    assert 'if ! dagster_pid_matches "$pid"' in function
    assert function.index('if ! dagster_pid_matches "$pid"') < function.index('kill "$pid"')
    assert 'grep -Fxq "DAGSTER_HOME=$DAGSTER_HOME_PATH"' in script


def test_local_stack_start_dry_run_plans_daemon_without_launching(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "FINANCE_AGENT_STATE_DIR": str(tmp_path / "state"),
        "FINANCE_AGENT_API_PORT": "49801",
        "FINANCE_AGENT_FRONTEND_PORT": "49802",
        "FINANCE_AGENT_DAGSTER_WEB_PORT": "49803",
    }

    result = subprocess.run(
        [
            "bash",
            str(PROJECT_ROOT / "scripts" / "local_stack_ctl.sh"),
            "start",
            "--frontend=none",
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    init_plan = "[dry-run] initialize .venv/bin/dagster instance info"
    start_plan = "[dry-run] start .venv/bin/dagster-daemon run -w workspace.yaml"
    webserver_plan = "[dry-run] start .venv/bin/dagster-webserver -w workspace.yaml"
    assert init_plan in result.stdout
    assert start_plan in result.stdout
    assert webserver_plan in result.stdout
    assert result.stdout.index(init_plan) < result.stdout.index(start_plan)
    assert result.stdout.index(start_plan) < result.stdout.index(webserver_plan)
    assert not (tmp_path / "state" / "dagster-daemon.pid").exists()
    assert not (tmp_path / "state" / "dagster-webserver.pid").exists()
    assert not (tmp_path / "state" / "dagster-home").exists()


def test_local_stack_stop_never_kills_non_managed_pid_from_stale_pidfile(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    unrelated = subprocess.Popen(["sleep", "30"])
    try:
        (state_dir / "dagster-daemon.pid").write_text(f"{unrelated.pid}\n", encoding="utf-8")
        env = {
            **os.environ,
            "FINANCE_AGENT_STATE_DIR": str(state_dir),
            "FINANCE_AGENT_API_PORT": "49811",
            "FINANCE_AGENT_FRONTEND_PORT": "49812",
        }

        result = subprocess.run(
            [
                "bash",
                str(PROJECT_ROOT / "scripts" / "local_stack_ctl.sh"),
                "stop",
                "--frontend=none",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        assert unrelated.poll() is None
        assert "Dagster daemon is not running." in result.stdout
        assert not (state_dir / "dagster-daemon.pid").exists()
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)
