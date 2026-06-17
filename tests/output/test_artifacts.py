from __future__ import annotations

from pathlib import Path

import pytest

from apps.output.artifacts import artifact_run_dir, normalize_run_id


@pytest.mark.parametrize("bad", ["", " ", ".", "..", "a/b", r"a\\b"])
def test_normalize_run_id_rejects_unsafe_components(bad: str) -> None:
    with pytest.raises(ValueError):
        normalize_run_id(bad)


def test_artifact_run_dir_keeps_paths_under_storage(tmp_path: Path) -> None:
    path = artifact_run_dir(
        tmp_path,
        layer="features",
        domain="macro",
        date="2026-05-06",
        run_id="run-a",
    )

    assert path == (tmp_path / "features" / "macro" / "2026-05-06" / "run-a").resolve()
    assert path.is_relative_to(tmp_path.resolve())


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("layer", {"layer": ".."}),
        ("domain", {"domain": ".."}),
        ("date", {"date": "../../escape"}),
        ("run_id", {"run_id": ".."}),
    ],
)
def test_artifact_run_dir_rejects_path_traversal(tmp_path: Path, field: str, kwargs: dict[str, str]) -> None:
    params = {
        "layer": "features",
        "domain": "macro",
        "date": "2026-05-06",
        "run_id": "run-a",
    }
    params.update(kwargs)

    with pytest.raises(ValueError, match=field):
        artifact_run_dir(tmp_path, **params)
