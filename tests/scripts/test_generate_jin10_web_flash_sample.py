from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import scripts.generate_jin10_web_flash_sample as generator_script
from scripts.generate_jin10_web_flash_sample import generate_jin10_web_flash_sample


FIXTURE_HTML = Path("tests/fixtures/jin10/web_flash/home_fixture.html")


def test_generate_sample_writes_raw_parsed_and_feature_artifacts(tmp_path: Path) -> None:
    summary = generate_jin10_web_flash_sample(
        html_file=FIXTURE_HTML,
        storage_root=tmp_path,
        retrieved_date="2026-06-23",
        run_id="demo-run",
        fetched_at="2026-06-23T20:31:00+08:00",
        dry_run=False,
        overwrite=False,
    )

    assert summary["status"] == "ok"
    assert summary["dry_run"] is False
    assert summary["item_count"] == 3
    assert summary["brief_count"] == 3
    assert summary["artifact_path"] == "storage/features/news/2026-06-23/demo-run/jin10_web_flash_briefs.json"

    raw_path = tmp_path / "storage/raw/jin10/web_flash/2026-06-23/demo-run/home.html"
    parsed_path = tmp_path / "storage/parsed/jin10/web_flash/2026-06-23/demo-run/web_flash_items.json"
    feature_path = tmp_path / "storage/features/news/2026-06-23/demo-run/jin10_web_flash_briefs.json"
    assert raw_path.exists()
    assert parsed_path.exists()
    assert feature_path.exists()

    payload = json.loads(feature_path.read_text(encoding="utf-8"))
    bundle = payload["jin10_web_flash_briefs"]
    assert bundle["brief_count"] == 3
    assert {brief["display_bucket"] for brief in bundle["briefs"]} == {"重要新闻Top", "宏观政策快讯", "VIP快讯"}
    assert bundle["data_quality"]["source_key_counts"] == {
        "jin10_web_important_flash": 2,
        "jin10_web_vip_flash": 1,
    }


def test_generate_browser_profile_mode_uses_injected_collector_and_writes_feature_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []
    raw_path = tmp_path / "storage/raw/jin10/web_flash/2026-06-23/browser-run/home.html"
    parsed_path = tmp_path / "storage/parsed/jin10/web_flash/2026-06-23/browser-run/web_flash_items.json"

    def fake_browser_collector(**kwargs: object) -> dict:
        calls.append(kwargs)
        return {
            "status": "ok",
            "retrievedDate": "2026-06-23",
            "runId": "browser-run",
            "rawArtifactPath": str(raw_path),
            "parsedArtifactPath": str(parsed_path),
            "itemCount": 1,
            "items": [
                {
                    "itemId": "jin10_flash_browser_1",
                    "sourceKey": "jin10_web_important_flash",
                    "contentFamily": "web_important_flash.market_flash_important",
                    "title": "美联储主席发表讲话",
                    "summary": "美联储主席发表讲话，市场关注后续政策路径。",
                    "publishedAt": "2026-06-23 10:00",
                    "url": "https://flash.jin10.com/detail/browser-1",
                    "importanceSource": "jin10_home_important_marker",
                    "verificationStatus": "single_source",
                    "accessStatus": "readable",
                    "tags": ["美联储"],
                    "sourceRefs": [],
                    "artifactRefs": [],
                }
            ],
            "qualityFlags": {},
            "sourceRefs": [],
        }

    monkeypatch.setattr(generator_script, "collect_jin10_web_flash_with_browser_profile", fake_browser_collector)

    summary = generate_jin10_web_flash_sample(
        html_file=tmp_path / "missing-fixture.html",
        browser_profile=tmp_path / "profile",
        chromium_executable=tmp_path / "chromium",
        homepage_url="https://www.jin10.com/",
        storage_root=tmp_path,
        retrieved_date="2026-06-23",
        run_id="browser-run",
        fetched_at="2026-06-23T20:31:00+08:00",
        dry_run=False,
        overwrite=False,
    )

    assert len(calls) == 1
    assert calls[0]["user_data_dir"] == tmp_path / "profile"
    assert calls[0]["executable_path"] == tmp_path / "chromium"
    assert calls[0]["homepage_url"] == "https://www.jin10.com/"
    assert summary["source_mode"] == "browser_profile"
    assert summary["status"] == "ok"
    assert summary["item_count"] == 1
    assert summary["brief_count"] == 1
    assert summary["raw_artifact_path"] == "storage/raw/jin10/web_flash/2026-06-23/browser-run/home.html"
    assert summary["parsed_artifact_path"] == "storage/parsed/jin10/web_flash/2026-06-23/browser-run/web_flash_items.json"

    feature_path = tmp_path / "storage/features/news/2026-06-23/browser-run/jin10_web_flash_briefs.json"
    assert feature_path.exists()
    feature_payload = json.loads(feature_path.read_text(encoding="utf-8"))
    assert feature_payload["jin10_web_flash_briefs"]["status"] == "ok"


def test_generate_browser_profile_dry_run_does_not_call_browser_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_if_called(**_: object) -> dict:
        raise AssertionError("browser collector should not be called during dry-run")

    monkeypatch.setattr(generator_script, "collect_jin10_web_flash_with_browser_profile", fail_if_called)

    summary = generate_jin10_web_flash_sample(
        html_file=tmp_path / "missing-fixture.html",
        browser_profile=tmp_path / "profile",
        storage_root=tmp_path,
        retrieved_date="2026-06-23",
        run_id="browser-dry",
        fetched_at="2026-06-23T20:31:00+08:00",
        dry_run=True,
        overwrite=False,
    )

    assert summary["status"] == "planned"
    assert summary["source_mode"] == "browser_profile"
    assert summary["artifact_path"] == "storage/features/news/2026-06-23/browser-dry/jin10_web_flash_briefs.json"
    assert not (tmp_path / "storage").exists()


def test_generate_browser_profile_unavailable_archives_unavailable_feature_without_raw_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_unavailable_collector(**_: object) -> dict:
        return {
            "status": "unavailable",
            "retrievedDate": "2026-06-23",
            "runId": "browser-unavailable",
            "rawArtifactPath": None,
            "parsedArtifactPath": None,
            "itemCount": 0,
            "items": [],
            "qualityFlags": {"fetch_failed": True, "reason": "browser profile missing"},
            "sourceRefs": [],
        }

    monkeypatch.setattr(generator_script, "collect_jin10_web_flash_with_browser_profile", fake_unavailable_collector)

    summary = generate_jin10_web_flash_sample(
        html_file=tmp_path / "missing-fixture.html",
        browser_profile=tmp_path / "profile",
        storage_root=tmp_path,
        retrieved_date="2026-06-23",
        run_id="browser-unavailable",
        fetched_at="2026-06-23T20:31:00+08:00",
        dry_run=False,
        overwrite=False,
    )

    assert summary["source_mode"] == "browser_profile"
    assert summary["status"] == "unavailable"
    assert summary["raw_artifact_path"] is None
    assert summary["parsed_artifact_path"] is None

    feature_path = tmp_path / "storage/features/news/2026-06-23/browser-unavailable/jin10_web_flash_briefs.json"
    assert feature_path.exists()
    feature_payload = json.loads(feature_path.read_text(encoding="utf-8"))
    bundle = feature_payload["jin10_web_flash_briefs"]
    assert bundle["status"] == "unavailable"
    assert bundle["quality_flags"]["fetch_failed"] is True


def test_generate_sample_dry_run_reports_paths_without_writing(tmp_path: Path) -> None:
    summary = generate_jin10_web_flash_sample(
        html_file=FIXTURE_HTML,
        storage_root=tmp_path,
        retrieved_date="2026-06-23",
        run_id="dry-run",
        fetched_at="2026-06-23T20:31:00+08:00",
        dry_run=True,
        overwrite=False,
    )

    assert summary["status"] == "planned"
    assert summary["dry_run"] is True
    assert summary["artifact_path"] == "storage/features/news/2026-06-23/dry-run/jin10_web_flash_briefs.json"
    assert not (tmp_path / "storage").exists()


def test_generate_sample_refuses_to_overwrite_existing_artifact(tmp_path: Path) -> None:
    feature_path = tmp_path / "storage/features/news/2026-06-23/existing/jin10_web_flash_briefs.json"
    feature_path.parent.mkdir(parents=True)
    feature_path.write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError):
        generate_jin10_web_flash_sample(
            html_file=FIXTURE_HTML,
            storage_root=tmp_path,
            retrieved_date="2026-06-23",
            run_id="existing",
            fetched_at="2026-06-23T20:31:00+08:00",
            dry_run=False,
            overwrite=False,
        )


def test_cli_dry_run_can_be_executed_as_script(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "python",
            "scripts/generate_jin10_web_flash_sample.py",
            "--html-file",
            FIXTURE_HTML.as_posix(),
            "--storage-root",
            tmp_path.as_posix(),
            "--retrieved-date",
            "2026-06-23",
            "--run-id",
            "cli-dry",
            "--fetched-at",
            "2026-06-23T20:31:00+08:00",
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(result.stdout)
    assert summary["status"] == "planned"
    assert summary["artifact_path"] == "storage/features/news/2026-06-23/cli-dry/jin10_web_flash_briefs.json"


def test_cli_browser_profile_dry_run_can_be_executed_without_browser(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "python",
            "scripts/generate_jin10_web_flash_sample.py",
            "--browser-profile",
            (tmp_path / "profile").as_posix(),
            "--storage-root",
            tmp_path.as_posix(),
            "--retrieved-date",
            "2026-06-23",
            "--run-id",
            "cli-browser-dry",
            "--fetched-at",
            "2026-06-23T20:31:00+08:00",
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(result.stdout)
    assert summary["status"] == "planned"
    assert summary["source_mode"] == "browser_profile"
    assert summary["artifact_path"] == "storage/features/news/2026-06-23/cli-browser-dry/jin10_web_flash_briefs.json"
    assert not (tmp_path / "storage").exists()
