"""Versioned, reviewable facts derived from one parsed report figure."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FIGURE_FACT_SCHEMA_VERSION = "figure_fact.v1"


class FigureFactQualityStatus(StrEnum):
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FigureNumericValue(_StrictModel):
    label: str
    value: str | int | float
    unit: str | None = None
    context: str | None = None

    @field_validator("label", "unit", "context")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("text fields must not be blank")
        return normalized


class FigureDerivedClaim(_StrictModel):
    claim: str
    basis: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("claim")
    @classmethod
    def _strip_claim(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("claim must not be blank")
        return normalized

    @field_validator("basis")
    @classmethod
    def _validate_basis(cls, values: list[str]) -> list[str]:
        return _normalized_non_empty_strings(values, field_name="basis")


class FigureFactContent(_StrictModel):
    schema_version: Literal["figure_fact.v1"] = FIGURE_FACT_SCHEMA_VERSION
    figure_id: str
    report_id: str
    page_no: int = Field(ge=1)
    bbox: tuple[int, int, int, int]
    asset: str
    observations: list[str] = Field(default_factory=list)
    numeric_values: list[FigureNumericValue] = Field(default_factory=list)
    derived_claims: list[FigureDerivedClaim] = Field(default_factory=list)
    interpretation_limits: list[str] = Field(default_factory=list)
    source_ref: dict[str, Any]
    quality_status: FigureFactQualityStatus
    review_ref: dict[str, Any] | None = None
    image_content_hash: str | None = None
    created_by_run_id: str

    @field_validator("figure_id", "report_id", "asset", "created_by_run_id")
    @classmethod
    def _validate_identity(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("identity fields must not be blank")
        if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
            raise ValueError("identity fields must be safe path components")
        return normalized

    @field_validator("bbox")
    @classmethod
    def _validate_bbox(cls, value: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = value
        if min(value) < 0 or x2 <= x1 or y2 <= y1:
            raise ValueError("bbox must be a positive-area [x1, y1, x2, y2] rectangle")
        return value

    @field_validator("observations", "interpretation_limits")
    @classmethod
    def _validate_text_lists(cls, values: list[str], info: Any) -> list[str]:
        return _normalized_non_empty_strings(values, field_name=info.field_name)

    @field_validator("image_content_hash")
    @classmethod
    def _validate_image_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_sha256(value, field_name="image_content_hash")

    @model_validator(mode="after")
    def _validate_quality_and_lineage(self) -> "FigureFactContent":
        source_figure_id = str(self.source_ref.get("figure_id") or "")
        source_report_id = str(
            self.source_ref.get("report_id") or self.source_ref.get("article_id") or ""
        )
        source_page_no = self.source_ref.get("page_no")
        source_bbox = self.source_ref.get("bbox")
        if source_figure_id != self.figure_id:
            raise ValueError("source_ref.figure_id must match figure_id")
        if source_report_id != self.report_id:
            raise ValueError("source_ref.report_id/article_id must match report_id")
        try:
            normalized_page_no = int(source_page_no)
        except (TypeError, ValueError) as exc:
            raise ValueError("source_ref.page_no must match page_no") from exc
        if normalized_page_no != self.page_no:
            raise ValueError("source_ref.page_no must match page_no")
        try:
            normalized_bbox = tuple(int(value) for value in source_bbox)
        except (TypeError, ValueError) as exc:
            raise ValueError("source_ref.bbox must match bbox") from exc
        if normalized_bbox != self.bbox:
            raise ValueError("source_ref.bbox must match bbox")

        has_direct_evidence = bool(self.observations or self.numeric_values)
        if self.quality_status is FigureFactQualityStatus.ACCEPTED:
            if not has_direct_evidence:
                raise ValueError("accepted FigureFact requires observations or numeric_values")
            if self.image_content_hash is None:
                raise ValueError("accepted FigureFact requires image_content_hash")
        elif not self.interpretation_limits:
            raise ValueError("non-accepted FigureFact requires interpretation_limits")
        return self


class FigureFact(FigureFactContent):
    figure_fact_id: str
    content_hash: str

    @field_validator("figure_fact_id")
    @classmethod
    def _validate_figure_fact_id(cls, value: str) -> str:
        return FigureFactContent._validate_identity(value)

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, value: str) -> str:
        return _validate_sha256(value, field_name="content_hash")

    @model_validator(mode="after")
    def _verify_content_hash(self) -> "FigureFact":
        expected = compute_figure_fact_content_hash(self)
        if self.content_hash != expected:
            raise ValueError("content_hash does not match FigureFact content")
        return self

    @classmethod
    def build(cls, *, figure_fact_id: str | None = None, **values: Any) -> "FigureFact":
        content = FigureFactContent.model_validate(values)
        content_payload = content.model_dump(mode="json")
        content_hash = compute_figure_fact_content_hash(content_payload)
        resolved_id = figure_fact_id or f"figure_fact_{content_hash[:20]}"
        return cls.model_validate(
            {
                **content_payload,
                "figure_fact_id": resolved_id,
                "content_hash": content_hash,
            }
        )


class ConfirmedFigureEvidence(_StrictModel):
    schema_version: Literal["figure_fact.v1"]
    figure_fact_id: str
    figure_id: str
    report_id: str
    page_no: int
    bbox: tuple[int, int, int, int]
    asset: str
    observations: list[str]
    numeric_values: list[FigureNumericValue]
    derived_claims: list[FigureDerivedClaim]
    interpretation_limits: list[str]
    source_ref: dict[str, Any]
    quality_status: Literal["accepted"]
    content_hash: str
    image_content_hash: str
    created_by_run_id: str


class FigureReplaySelection(_StrictModel):
    status: Literal["ready", "degraded"]
    report_id: str
    figure_id: str
    page_no: int = Field(ge=1)
    bbox: tuple[int, int, int, int]
    asset: str
    image_path: str | None
    image_content_hash: str | None
    source_ref: dict[str, Any]
    degraded_reasons: list[str] = Field(default_factory=list)


def compute_figure_fact_content_hash(value: FigureFactContent | dict[str, Any]) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    else:
        payload = dict(value)
    payload.pop("content_hash", None)
    payload.pop("figure_fact_id", None)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def project_confirmed_evidence(
    fact: FigureFact | dict[str, Any],
) -> ConfirmedFigureEvidence | None:
    validated = validate_figure_fact(fact)
    if validated.quality_status is not FigureFactQualityStatus.ACCEPTED:
        return None
    return ConfirmedFigureEvidence.model_validate(
        validated.model_dump(mode="json", exclude={"review_ref"})
    )


def select_figure_facts(
    facts: list[FigureFact | dict[str, Any]],
    *,
    report_id: str | None = None,
    figure_id: str | None = None,
    quality_status: FigureFactQualityStatus | str | None = None,
    confirmed_only: bool = False,
) -> list[FigureFact]:
    expected_status = FigureFactQualityStatus(quality_status) if quality_status else None
    selected = []
    for item in facts:
        fact = validate_figure_fact(item)
        if report_id is not None and fact.report_id != report_id:
            continue
        if figure_id is not None and fact.figure_id != figure_id:
            continue
        if expected_status is not None and fact.quality_status is not expected_status:
            continue
        if confirmed_only and fact.quality_status is not FigureFactQualityStatus.ACCEPTED:
            continue
        selected.append(fact)
    return sorted(
        selected,
        key=lambda item: (item.report_id, item.page_no, item.figure_id, item.figure_fact_id),
    )


def validate_figure_fact(fact: FigureFact | dict[str, Any]) -> FigureFact:
    """Revalidate cached models so nested mutations cannot bypass the content hash."""

    payload = fact.model_dump(mode="json") if isinstance(fact, FigureFact) else fact
    return FigureFact.model_validate(payload)


def select_parsed_figure(
    figures_payload: dict[str, Any] | list[dict[str, Any]], *, figure_id: str
) -> dict[str, Any]:
    raw_figures = (
        figures_payload.get("figures", [])
        if isinstance(figures_payload, dict)
        else figures_payload
    )
    matches = [dict(item) for item in raw_figures if str(item.get("figure_id") or "") == figure_id]
    if not matches:
        raise LookupError(f"parsed figure not found: {figure_id}")
    if len(matches) != 1:
        raise ValueError(f"parsed figure id is not unique: {figure_id}")
    return matches[0]


def prepare_figure_replay(
    *,
    parsed_dir: str | Path,
    figures_payload: dict[str, Any] | list[dict[str, Any]],
    figure_id: str,
    report_id: str,
    asset: str,
    source_ref: dict[str, Any] | None = None,
) -> FigureReplaySelection:
    """Select one parsed figure and prepare deterministic local replay input."""

    parsed_root = Path(parsed_dir).resolve()
    figure = select_parsed_figure(figures_payload, figure_id=figure_id)
    page_no = int(figure.get("page_no"))
    bbox = tuple(figure.get("bbox") or ())
    image_value = str(figure.get("chart_image_path") or figure.get("image_path") or "").strip()
    image_path: str | None = None
    image_hash: str | None = None
    reasons: list[str] = []

    if not image_value:
        reasons.append("image_path_missing")
    else:
        candidate = Path(image_value)
        if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
            reasons.append("image_path_unsafe")
        else:
            resolved = (parsed_root / candidate).resolve()
            if not resolved.is_relative_to(parsed_root):
                reasons.append("image_path_unsafe")
            elif not resolved.is_file():
                reasons.append("image_missing")
            else:
                try:
                    content = resolved.read_bytes()
                except OSError:
                    reasons.append("image_unreadable")
                else:
                    if not content:
                        reasons.append("image_unreadable")
                    else:
                        image_path = candidate.as_posix()
                        image_hash = hashlib.sha256(content).hexdigest()

    lineage = {
        **(source_ref or {}),
        **(figure.get("source_ref") if isinstance(figure.get("source_ref"), dict) else {}),
        "report_id": str(report_id),
        "figure_id": str(figure_id),
        "page_no": page_no,
        "bbox": list(bbox),
    }
    if image_path:
        lineage["image_path"] = image_path
    if image_hash:
        lineage["image_sha256"] = image_hash

    return FigureReplaySelection.model_validate(
        {
            "status": "degraded" if reasons else "ready",
            "report_id": report_id,
            "figure_id": figure_id,
            "page_no": page_no,
            "bbox": bbox,
            "asset": asset,
            "image_path": image_path,
            "image_content_hash": image_hash,
            "source_ref": lineage,
            "degraded_reasons": reasons,
        }
    )


def _validate_sha256(value: str, *, field_name: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _normalized_non_empty_strings(values: list[str], *, field_name: str) -> list[str]:
    normalized = [str(value).strip() for value in values]
    if any(not value for value in normalized):
        raise ValueError(f"{field_name} must not contain blank entries")
    return normalized
