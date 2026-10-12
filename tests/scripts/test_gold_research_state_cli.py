"""Argument errors must be rejected before any database connection."""

from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('args', [
    ['--initialize'],
    ['--initialize', '--accept', '--expected-head', 'existing-head'],
    ['--initialize', '--accept', '--expected-head', 'NONE', '--acknowledge-missing'],
    ['--readiness', '--accept'],
    ['--readiness', '--init-db'],
])
def test_invalid_state_operations_fail_at_cli_boundary(args):
    script = Path(__file__).resolve().parents[2] / 'scripts/gold_research_state.py'
    result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)
    assert result.returncode == 2
    assert 'error:' in result.stderr
    assert 'OperationalError' not in result.stderr
