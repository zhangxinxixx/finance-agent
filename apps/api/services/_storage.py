from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _latest_date_dir(base: Path) -> Path | None:
    if not base.exists():
        return None
    dates = sorted((d for d in base.iterdir() if d.is_dir()), reverse=True)
    return dates[0] if dates else None


def _latest_run_file(date_dir: Path, filename: str) -> Path | None:
    if not date_dir.exists():
        return None
    run_dirs = sorted((d for d in date_dir.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
    for run_dir in run_dirs:
        candidate = run_dir / filename
        if candidate.exists():
            return candidate
    fallback = date_dir / filename
    return fallback if fallback.exists() else None


def _latest_asset_date_run(base: Path, asset: str) -> tuple[str | None, str | None, Path | None]:
    asset_dir = base / asset
    if not asset_dir.exists():
        return None, None, None
    dates = sorted((d for d in asset_dir.iterdir() if d.is_dir()), reverse=True)
    for date_dir in dates:
        runs = sorted(
            (d for d in date_dir.iterdir() if d.is_dir()),
            key=lambda run_dir: (run_dir.stat().st_mtime, run_dir.name),
            reverse=True,
        )
        for run_dir in runs:
            return date_dir.name, run_dir.name, run_dir
    return (dates[0].name, None, None) if dates else (None, None, None)


def _try_db_session():
    try:
        from database.models.engine import SessionLocal as _SL

        return _SL()
    except Exception:
        return None


def _iso(v: object) -> str:
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return str(v)
