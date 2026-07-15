from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fitz
import pytest

from apps.collectors.cme.downloader import (
    CmeRawFile,
    archive_cme_pdf,
    build_daily_bulletin_url,
    download_cme_pdf,
)


def _make_pdf_bytes(*, text: str | None = None) -> bytes:
    document = fitz.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    return document.tobytes()


def test_build_daily_bulletin_url_uses_current_section_path() -> None:
    assert build_daily_bulletin_url() == (
        "https://www.cmegroup.com/daily_bulletin/current/Section64_Metals_Option_Products.pdf"
    )
    assert build_daily_bulletin_url("Section01_Test.pdf") == (
        "https://www.cmegroup.com/daily_bulletin/current/Section01_Test.pdf"
    )


def test_archive_cme_pdf_extracts_report_date_and_writes_expected_path(tmp_path: Path) -> None:
    raw = _make_pdf_bytes(text="Fri, Nov 28, 2025")

    result = archive_cme_pdf(
        raw,
        report_date="latest",
        section_file="Section64_Metals_Option_Products.pdf",
        source_url="https://www.cmegroup.com/daily_bulletin/current/Section64_Metals_Option_Products.pdf",
        storage_root=tmp_path,
    )

    assert result.report_date == "2025-11-28"
    assert result.date_source == "pdf"
    assert result.bytes == len(raw)
    assert result.sha256 == hashlib.sha256(raw).hexdigest()
    assert result.source == "cme"
    assert result.section == "Section64_Metals_Option_Products.pdf"
    assert result.raw_path == (
        f"raw/cme/daily_bulletin/2025-11-28/Section64_Metals_Option_Products_2025-11-28_{result.sha256[:12]}.pdf"
    )
    assert (tmp_path / result.raw_path).exists()

    payload = json.loads(result.to_json())
    assert payload["raw_path"] == result.raw_path
    assert payload["date_source"] == "pdf"


def test_archive_cme_pdf_uses_argument_when_pdf_date_missing_and_rejects_invalid_header(tmp_path: Path) -> None:
    valid_raw = _make_pdf_bytes()
    result = archive_cme_pdf(
        valid_raw,
        report_date="2026-05-06",
        section_file="Section64_Metals_Option_Products.pdf",
        source_url="fixture://cme/Section64_Metals_Option_Products.pdf",
        storage_root=tmp_path,
    )

    assert result.report_date == "2026-05-06"
    assert result.date_source == "argument"
    assert result.raw_path.endswith(f"Section64_Metals_Option_Products_2026-05-06_{result.sha256[:12]}.pdf")

    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    try:
        archive_cme_pdf(
            b"not-a-pdf",
            report_date="2026-05-06",
            section_file="Section64_Metals_Option_Products.pdf",
            source_url="fixture://cme/Section64_Metals_Option_Products.pdf",
            storage_root=tmp_path,
        )
    except ValueError as exc:
        assert "PDF header" in str(exc)
    else:
        raise AssertionError("expected invalid PDF bytes to raise")

    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert after == before


def test_download_cme_pdf_uses_mocked_bytes_and_returns_json_shape(tmp_path: Path, monkeypatch) -> None:
    raw = _make_pdf_bytes(text="Fri, Nov 28, 2025")
    seen: list[str] = []

    def fake_download_cme_pdf_bytes(*, source_url: str) -> bytes:
        seen.append(source_url)
        return raw

    monkeypatch.setattr("apps.collectors.cme.downloader._download_cme_pdf_bytes", fake_download_cme_pdf_bytes)

    result = download_cme_pdf(
        section_file="Section64_Metals_Option_Products.pdf",
        report_date="latest",
        storage_root=tmp_path,
    )

    assert seen == [
        "https://www.cmegroup.com/daily_bulletin/current/Section64_Metals_Option_Products.pdf"
    ]
    assert isinstance(result, CmeRawFile)
    assert result.to_dict()["raw_path"].startswith("raw/cme/daily_bulletin/2025-11-28/")
    assert json.loads(result.to_json())["source_url"] == seen[0]
    assert (tmp_path / result.raw_path).exists()


def test_download_cme_pdf_retries_transient_network_failure(tmp_path: Path, monkeypatch) -> None:
    raw = _make_pdf_bytes(text="Thu, Jul 16, 2026")
    attempts = 0
    delays: list[float] = []

    def flaky_download(*, source_url: str) -> bytes:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("CME PDF XHR network error")
        return raw

    monkeypatch.setattr("apps.collectors.cme.downloader._download_cme_pdf_bytes", flaky_download)
    monkeypatch.setattr("apps.collectors.cme.downloader.time.sleep", delays.append)

    result = download_cme_pdf(storage_root=tmp_path, max_attempts=3, retry_delay_seconds=0.25)

    assert result.report_date == "2026-07-16"
    assert attempts == 3
    assert delays == [0.25, 0.25]


def test_download_cme_pdf_reports_exhausted_attempts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.collectors.cme.downloader._download_cme_pdf_bytes",
        lambda **_: (_ for _ in ()).throw(RuntimeError("CME PDF XHR network error")),
    )
    monkeypatch.setattr("apps.collectors.cme.downloader.time.sleep", lambda _: None)

    with pytest.raises(RuntimeError, match="failed after 2 attempts.*XHR network error"):
        download_cme_pdf(storage_root=tmp_path, max_attempts=2, retry_delay_seconds=0)
