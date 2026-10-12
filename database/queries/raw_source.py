"""Validated writes for the typed raw-source catalog."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import stat

from sqlalchemy import select

from database.models.raw_source import RawRetentionEvent, RawSourceFile, RawSourceLoad, RawSourceLoadBatch
from database.models.warehouse import LoadBatch


class RawSourceError(ValueError):
    pass


SOURCE_FILE_HASH_DATASETS = frozenset({"cme-options", "fedwatch", "settlement"})


def _fail(code: str) -> None:
    raise RawSourceError(code)


def canonical_storage_root(storage_root) -> Path:
    root = Path(storage_root)
    try:
        if not root.is_absolute() or stat.S_ISLNK(root.lstat().st_mode):
            _fail("RAW_STORAGE_ROOT_INVALID")
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        _fail("RAW_STORAGE_ROOT_INVALID")
    if not root.is_dir():
        _fail("RAW_STORAGE_ROOT_INVALID")
    return root


def normalized_raw_path(raw_path) -> PurePosixPath:
    text = str(raw_path)
    if "\\" in text:
        _fail("RAW_PATH_INVALID")
    path = PurePosixPath(text)
    if path.is_absolute() or not path.parts or path.parts[0] != "raw":
        _fail("RAW_PATH_INVALID")
    if any(part in ("", ".", "..") for part in path.parts):
        _fail("RAW_PATH_INVALID")
    return path


def normalized_batch_artifact_path(storage_root: Path, artifact_path) -> PurePosixPath:
    """Normalize a batch source path against the catalog's trusted root.

    Relative paths must already be ``raw/...``.  Absolute paths are accepted
    only when they are lexically inside the same trusted root; parent traversal
    is rejected before normalization.
    """
    if not isinstance(artifact_path, str) or not artifact_path.strip() or "\\" in artifact_path:
        _fail("RAW_LOAD_SOURCE_PATH_INVALID")
    text = artifact_path.strip()
    candidate = Path(text)
    if any(part in ("", ".", "..") for part in PurePosixPath(text).parts):
        _fail("RAW_LOAD_SOURCE_PATH_INVALID")
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(storage_root)
        except ValueError:
            _fail("RAW_LOAD_SOURCE_PATH_INVALID")
        return normalized_raw_path(relative.as_posix())
    return normalized_raw_path(text)


def load_batch_source_error(batch: LoadBatch, raw_file: RawSourceFile, session=None) -> str | None:
    """Return the lineage error that prevents a batch covering ``raw_file``."""
    link = None
    if session is not None:
        from sqlalchemy import inspect
        from database.models.warehouse_sync import BatchSourceFile

        if inspect(session.connection()).has_table(BatchSourceFile.__tablename__):
            link = session.get(BatchSourceFile, (batch.id, raw_file.raw_path))
    return _batch_source_error(batch, raw_file, link, require_file_identity=session is not None)


def load_batch_source_errors(session, batches, raw_file: RawSourceFile) -> dict[int, str | None]:
    """Validate repeated receipts with one bounded fetch per distinct batch group."""
    from sqlalchemy import inspect
    from database.models.warehouse_sync import BatchSourceFile

    by_id = {batch.id: batch for batch in batches}
    links = {}
    if inspect(session.connection()).has_table(BatchSourceFile.__tablename__):
        ids = list(by_id)
        for offset in range(0, len(ids), 500):
            rows = session.scalars(select(BatchSourceFile).where(
                BatchSourceFile.batch_id.in_(ids[offset:offset + 500]),
                BatchSourceFile.raw_path == raw_file.raw_path,
            ).execution_options(populate_existing=True))
            links.update((row.batch_id, row) for row in rows)
    return {key: _batch_source_error(batch, raw_file, links.get(key), require_file_identity=True)
            for key, batch in by_id.items()}


def _batch_source_error(batch, raw_file, link, *, require_file_identity):
    if link is not None:
        if (link.batch_source_path != batch.source_artifact_path
                or link.batch_source_sha256 != batch.source_sha256
                or link.batch_source_cursor != batch.source_cursor):
            return "RAW_LOAD_SOURCE_BATCH_CHANGED"
        if link.storage_root != raw_file.storage_root:
            return "RAW_LOAD_SOURCE_ROOT_MISMATCH"
        if link.sha256 != raw_file.sha256 or link.byte_size != raw_file.byte_size:
            return "RAW_LOAD_SOURCE_HASH_MISMATCH"
        if link.purpose != "primary" or batch.dataset not in SOURCE_FILE_HASH_DATASETS:
            return None
    try:
        root = Path(raw_file.storage_root)
        batch_path = normalized_batch_artifact_path(root, batch.source_artifact_path)
        raw_path = normalized_raw_path(raw_file.raw_path)
    except RawSourceError as exc:
        return str(exc)
    if batch_path != raw_path:
        return "RAW_LOAD_SOURCE_PATH_MISMATCH"
    if batch.dataset in SOURCE_FILE_HASH_DATASETS:
        digest = batch.source_sha256
        if not isinstance(digest, str) or len(digest) != 64:
            return "RAW_LOAD_SOURCE_HASH_MISSING"
        try:
            int(digest, 16)
        except ValueError:
            return "RAW_LOAD_SOURCE_HASH_MISSING"
        if digest.lower() != raw_file.sha256.lower():
            return "RAW_LOAD_SOURCE_HASH_MISMATCH"
    elif require_file_identity:
        # A macro/candle version hash is not a file hash. Without a file identity
        # captured during the load, an old matching path cannot prove coverage.
        return "RAW_LOAD_SOURCE_FILE_UNVERIFIED"
    return None


def _open_regular(root: Path, raw_path: PurePosixPath) -> tuple[int, os.stat_result]:
    """Open through directory fds, refusing every symlink in the path."""
    opened: list[int] = []
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        current = os.open(root, flags_dir)
        opened.append(current)
        for part in raw_path.parts[:-1]:
            current = os.open(part, flags_dir, dir_fd=current)
            opened.append(current)
        flags_file = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(raw_path.parts[-1], flags_file, dir_fd=current)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            _fail("RAW_FILE_NOT_REGULAR")
        return fd, info
    except RawSourceError:
        raise
    except OSError:
        _fail("RAW_FILE_UNSAFE_OR_MISSING")
    finally:
        for directory_fd in reversed(opened):
            os.close(directory_fd)


def file_identity(root: Path, raw_path: PurePosixPath) -> tuple[str, int, os.stat_result]:
    fd, info = _open_regular(root, raw_path)
    digest = sha256()
    try:
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            _fail("RAW_FILE_CHANGED_DURING_READ")
        return digest.hexdigest(), after.st_size, after
    finally:
        os.close(fd)


def _raw_path_is_missing(root: Path, raw_path: PurePosixPath) -> bool:
    """Distinguish absence from symlinks, unsafe components and other errors."""
    opened: list[int] = []
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        current = os.open(root, flags_dir)
        opened.append(current)
        for part in raw_path.parts[:-1]:
            try:
                current = os.open(part, flags_dir, dir_fd=current)
            except FileNotFoundError:
                return True
            except OSError:
                return False
            opened.append(current)
        try:
            os.stat(raw_path.parts[-1], dir_fd=current, follow_symlinks=False)
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return False
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def has_completed_retention_tombstone(
    session, *, storage_root, raw_path, expected_sha256=None
) -> bool:
    """Return true only for a missing path whose current catalog version was deleted."""
    root = canonical_storage_root(storage_root)
    relative = normalized_raw_path(raw_path)
    if not _raw_path_is_missing(root, relative):
        return False

    # A live catalog row is the current version even when the physical file is
    # now missing. An older deletion must never hide that unexplained loss.
    active = session.scalar(
        select(RawSourceFile.id)
        .where(
            RawSourceFile.storage_root == str(root),
            RawSourceFile.raw_path == relative.as_posix(),
            RawSourceFile.deleted_at.is_(None),
        )
        .limit(1)
    )
    if active is not None:
        return False

    query = (
        select(RawRetentionEvent.id)
        .join(RawSourceFile, RawSourceFile.id == RawRetentionEvent.raw_file_id)
        .where(
            RawRetentionEvent.storage_root == str(root),
            RawRetentionEvent.raw_path == relative.as_posix(),
            # Both actions record completed deletion; previews and other audit
            # events must never explain away an unexpectedly missing file.
            RawRetentionEvent.action.in_(("delete", "explicit_cutoff")),
            RawRetentionEvent.status == "deleted",
            RawRetentionEvent.completed_at.is_not(None),
            RawSourceFile.storage_root == str(root),
            RawSourceFile.raw_path == relative.as_posix(),
            RawSourceFile.state == "deleted",
            RawSourceFile.deleted_at.is_not(None),
            RawSourceFile.sha256 == RawRetentionEvent.sha256,
        )
    )
    if expected_sha256 is not None:
        query = query.where(RawRetentionEvent.sha256 == str(expected_sha256).lower())
    tombstone = session.scalar(query.limit(1))
    return tombstone is not None and _raw_path_is_missing(root, relative)


def _utc(value: datetime, code: str) -> datetime:
    if not isinstance(value, datetime):
        _fail(code)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def register_raw_file(
    session,
    *,
    storage_root,
    raw_path,
    source_key,
    collected_at,
    source_url=None,
    producer_run_id=None,
    expected_sha256=None,
):
    """Register the immutable identity currently present at ``raw_path``.

    The caller owns the transaction. Re-registering the same producer reference is
    idempotent; a changed file creates a new revision row rather than rewriting history.
    """
    root = canonical_storage_root(storage_root)
    relative = normalized_raw_path(raw_path)
    if not isinstance(source_key, str) or not source_key.strip():
        _fail("RAW_SOURCE_KEY_INVALID")
    collected = _utc(collected_at, "RAW_COLLECTED_AT_INVALID")
    digest, byte_size, _ = file_identity(root, relative)
    if expected_sha256 is not None and str(expected_sha256).lower() != digest:
        _fail("RAW_SHA256_MISMATCH")
    producer = str(producer_run_id) if producer_run_id is not None else None
    if producer is not None and (not producer.strip() or len(producer) > 255):
        _fail("RAW_PRODUCER_ID_INVALID")
    stmt = select(RawSourceFile).where(
        RawSourceFile.storage_root == str(root),
        RawSourceFile.raw_path == relative.as_posix(),
        RawSourceFile.sha256 == digest,
        RawSourceFile.source_key == source_key.strip(),
        RawSourceFile.deleted_at.is_(None),
    )
    stmt = stmt.where(
        RawSourceFile.producer_run_id.is_(None)
        if producer is None
        else RawSourceFile.producer_run_id == producer
    )
    with session.no_autoflush:
        existing = session.scalar(stmt.order_by(RawSourceFile.created_at, RawSourceFile.id).limit(1))
    if existing is not None:
        if existing.state == "deleting":
            _fail("RAW_FILE_BUSY")
        return existing
    row = RawSourceFile(
        storage_root=str(root),
        raw_path=relative.as_posix(),
        sha256=digest,
        byte_size=byte_size,
        source_key=source_key.strip(),
        source_url=str(source_url) if source_url is not None else None,
        collected_at=collected,
        producer_run_id=producer,
        state="registered",
    )
    session.add(row)
    session.flush([row])
    return row


def record_raw_file_load(
    session,
    *,
    raw_file_id,
    dataset,
    expected_records,
    loaded_records,
    rejected_records,
    load_batch_ids,
    completed_at=None,
):
    """Record complete coverage only after validating the referenced DWH batches."""
    counts = (expected_records, loaded_records, rejected_records)
    if any(type(value) is not int or value < 0 for value in counts):
        _fail("RAW_LOAD_COUNT_INVALID")
    if expected_records != loaded_records or rejected_records != 0:
        _fail("RAW_LOAD_INCOMPLETE")
    if not isinstance(dataset, str) or not dataset.strip():
        _fail("RAW_LOAD_DATASET_INVALID")
    try:
        batch_ids = list(dict.fromkeys(load_batch_ids))
    except TypeError:
        _fail("RAW_LOAD_BATCH_INVALID")
    if not batch_ids or any(type(value) is not int or value < 1 for value in batch_ids):
        _fail("RAW_LOAD_BATCH_INVALID")
    raw_file = session.get(RawSourceFile, str(raw_file_id))
    if raw_file is None or raw_file.state in ("deleted", "deleting"):
        _fail("RAW_FILE_UNKNOWN")
    with session.no_autoflush:
        batches = list(session.scalars(select(LoadBatch).where(LoadBatch.id.in_(batch_ids))))
    by_id = {batch.id: batch for batch in batches}
    if set(by_id) != set(batch_ids):
        _fail("RAW_LOAD_BATCH_UNKNOWN")
    if any(batch.dataset != dataset for batch in batches):
        _fail("RAW_LOAD_DATASET_MISMATCH")
    if any(batch.status != "loaded" or batch.rejected != 0 for batch in batches):
        _fail("RAW_LOAD_BATCH_INCOMPLETE")
    source_errors = [load_batch_source_error(batch, raw_file, session) for batch in batches]
    if any(source_errors):
        _fail(next(error for error in source_errors if error is not None))
    actual_expected = sum(batch.processed for batch in batches)
    actual_loaded = sum(batch.inserted + batch.skipped for batch in batches)
    if (actual_expected, actual_loaded) != (expected_records, loaded_records):
        _fail("RAW_LOAD_COUNT_MISMATCH")
    completed = datetime.now(UTC) if completed_at is None else _utc(completed_at, "RAW_LOAD_TIME_INVALID")

    existing_loads = list(
        session.scalars(
            select(RawSourceLoad).where(
                RawSourceLoad.raw_file_id == raw_file.id,
                RawSourceLoad.dataset == dataset,
                RawSourceLoad.status == "completed",
                RawSourceLoad.expected_records == expected_records,
                RawSourceLoad.loaded_records == loaded_records,
                RawSourceLoad.rejected_records == rejected_records,
            )
        )
    )
    for existing in existing_loads:
        linked = list(
            session.scalars(
                select(RawSourceLoadBatch.batch_id)
                .where(RawSourceLoadBatch.load_id == existing.id)
                .order_by(RawSourceLoadBatch.ordinal)
            )
        )
        if linked == batch_ids:
            return existing

    load = RawSourceLoad(
        raw_file_id=raw_file.id,
        dataset=dataset,
        expected_records=expected_records,
        loaded_records=loaded_records,
        rejected_records=rejected_records,
        status="completed",
        completed_at=completed,
    )
    session.add(load)
    session.flush([load])
    for ordinal, batch_id in enumerate(batch_ids):
        session.add(RawSourceLoadBatch(load_id=load.id, batch_id=batch_id, ordinal=ordinal))
    raw_file.state = "loaded"
    session.flush()
    return load
