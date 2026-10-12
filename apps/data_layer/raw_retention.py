"""Read-only preview and auditable application of raw-file retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from collections import defaultdict
from pathlib import Path, PurePosixPath
import os
import stat
from uuid import UUID, uuid4

from sqlalchemy import and_, func, inspect, or_, select, update

from database.models.raw_source import (
    RawRetentionEvent,
    RawRetentionScan,
    RawSourceBase,
    RawSourceFile,
    RawSourceLoad,
    RawSourceLoadBatch,
)
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep
from database.models.warehouse import LoadBatch
from database.queries.raw_source import (
    RawSourceError,
    canonical_storage_root,
    file_identity,
    load_batch_source_errors,
    normalized_raw_path,
)


ACTIVE_TASK_STATES = {TaskStatus.pending, TaskStatus.running}
RETENTION_INTENT_LEASE = timedelta(minutes=15)


def _now(value) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if not isinstance(value, datetime):
        raise RawSourceError("RAW_RETENTION_NOW_INVALID")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _bounds(retention_days, limit) -> None:
    if type(retention_days) is not int or not 1 <= retention_days <= 36500:
        raise RawSourceError("RAW_RETENTION_DAYS_INVALID")
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise RawSourceError("RAW_RETENTION_LIMIT_INVALID")


def _require_schema(session) -> None:
    names = set(inspect(session.connection()).get_table_names())
    required = set(RawSourceBase.metadata.tables) | {"dwh_load_batch", "task_runs", "task_steps"}
    if not required <= names:
        raise RawSourceError("RAW_RETENTION_SCHEMA_MISSING")


def _physical_refs(session, row) -> list[RawSourceFile]:
    return list(
        session.scalars(
            select(RawSourceFile)
            .where(
                RawSourceFile.storage_root == row.storage_root,
                RawSourceFile.raw_path == row.raw_path,
                RawSourceFile.sha256 == row.sha256,
                RawSourceFile.deleted_at.is_(None),
            )
            .order_by(RawSourceFile.id)
        )
    )


def _producer_active(session, producer_run_id: str | None) -> bool:
    if not producer_run_id:
        return False
    try:
        task_id = UUID(producer_run_id)
    except (TypeError, ValueError, AttributeError):
        # A non-task producer identifier cannot name an active task row.
        return False
    task = session.get(TaskRun, task_id)
    return task is not None and task.status in ACTIVE_TASK_STATES


def _load_coverage_error(session, raw_file: RawSourceFile) -> str | None:
    loads = list(session.scalars(select(RawSourceLoad).where(
        RawSourceLoad.raw_file_id == raw_file.id,
    ).execution_options(populate_existing=True)))
    if not loads:
        return "LOAD_COVERAGE_INCOMPLETE"
    links_by_load = defaultdict(list)
    for load_id, batch_id in session.execute(select(RawSourceLoadBatch.load_id, RawSourceLoadBatch.batch_id).join(
        RawSourceLoad, RawSourceLoad.id == RawSourceLoadBatch.load_id,
    ).where(RawSourceLoad.raw_file_id == raw_file.id).order_by(RawSourceLoadBatch.load_id, RawSourceLoadBatch.ordinal)):
        links_by_load[load_id].append(batch_id)
    ids = list({batch_id for values in links_by_load.values() for batch_id in values})
    by_id = {}
    for offset in range(0, len(ids), 500):
        batches = session.scalars(select(LoadBatch).where(
            LoadBatch.id.in_(ids[offset:offset + 500]),
        ).execution_options(populate_existing=True))
        by_id.update((batch.id, batch) for batch in batches)
    source_errors = load_batch_source_errors(session, by_id.values(), raw_file)
    for load in loads:
        if (
            load.status != "completed"
            or load.completed_at is None
            or load.rejected_records != 0
            or load.expected_records != load.loaded_records
        ):
            return "LOAD_COVERAGE_INCOMPLETE"
        links = links_by_load[load.id]
        if not links:
            return "LOAD_COVERAGE_INCOMPLETE"
        batches = [by_id.get(batch_id) for batch_id in links]
        if any(batch is None for batch in batches):
            return "LOAD_COVERAGE_INCOMPLETE"
        if any(batch.dataset != load.dataset or batch.status != "loaded" or batch.rejected != 0 for batch in batches):
            return "LOAD_COVERAGE_INCOMPLETE"
        errors = [source_errors[batch.id] for batch in batches]
        if any(errors):
            return next(error for error in errors if error is not None)
        if sum(batch.processed for batch in batches) != load.expected_records:
            return "LOAD_COVERAGE_INCOMPLETE"
        if sum(batch.inserted + batch.skipped for batch in batches) != load.loaded_records:
            return "LOAD_COVERAGE_INCOMPLETE"
    return None


def _known_source_coverage_error(session, refs) -> str | None:
    """A receipt for one page must not authorize deletion of a shared raw file."""
    from database.models.analysis import MacroObservation, MarketCandle
    from database.models.cme import CmeRawFile
    row = refs[0]
    paths = {row.raw_path, "storage/" + row.raw_path, str(Path(row.storage_root) / row.raw_path)}
    paths.update(str(Path(root) / row.raw_path) for root in
                 os.getenv("FINANCE_AGENT_LEGACY_STORAGE_ROOTS", "").split(os.pathsep) if root)
    names = set(inspect(session.connection()).get_table_names())
    covered = set(session.scalars(select(RawSourceLoadBatch.batch_id).join(
        RawSourceLoad, RawSourceLoad.id == RawSourceLoadBatch.load_id,
    ).where(RawSourceLoad.raw_file_id.in_([ref.id for ref in refs]))))
    for dataset, model in (("macro", MacroObservation), ("candles", MarketCandle), ("cme-options", CmeRawFile)):
        if model.__tablename__ not in names:
            continue
        ids = list(session.scalars(select(model.id).where(model.raw_path.in_(paths))))
        for offset in range(0, len(ids), 500):
            chunk = ids[offset:offset + 500]
            latest = list(session.scalars(select(func.max(LoadBatch.id)).where(
                LoadBatch.dataset == dataset, LoadBatch.source_cursor.in_(chunk),
            ).group_by(LoadBatch.source_cursor)))
            if len(latest) != len(chunk) or not set(latest) <= covered:
                return "SOURCE_RECORDS_NOT_FULLY_LOADED"
    return None


def _evaluate(
    session,
    row,
    root: Path,
    cutoff: datetime,
    *,
    claimed_ids=(),
    physical_path: PurePosixPath | None = None,
) -> tuple[str | None, list[str]]:
    claimed = set(claimed_ids)
    if row.storage_root != str(root):
        return "STORAGE_ROOT_MISMATCH", []
    try:
        relative = normalized_raw_path(row.raw_path)
    except RawSourceError as exc:
        return str(exc), []
    refs = _physical_refs(session, row)
    if not refs:
        return "RAW_METADATA_MISSING", []
    ref_ids = [ref.id for ref in refs]
    # A merely registered row is classified by its missing coverage below, which
    # is the actionable safety reason. Other lifecycle states remain blocked.
    allowed = {"registered", "loaded"} if not claimed else {"loaded", "deleting"}
    if any(ref.state not in allowed or (ref.state == "deleting" and ref.id not in claimed) for ref in refs):
        return "RAW_FILE_STATE_BLOCKED", ref_ids
    if any(ref.collected_at > cutoff for ref in refs):
        return "RETENTION_NOT_DUE", ref_ids
    if any(_producer_active(session, ref.producer_run_id) for ref in refs):
        return "PRODUCER_TASK_ACTIVE", ref_ids
    for ref in refs:
        coverage_error = _load_coverage_error(session, ref)
        if coverage_error:
            return coverage_error, ref_ids
    coverage_error = _known_source_coverage_error(session, refs)
    if coverage_error:
        return coverage_error, ref_ids
    try:
        digest, byte_size, info = file_identity(root, physical_path or relative)
    except RawSourceError as exc:
        return str(exc), ref_ids
    if digest != row.sha256 or byte_size != row.byte_size:
        return "RAW_FILE_HASH_CHANGED", ref_ids
    # Collection time alone is insufficient: a recently created/replaced inode is retained.
    if datetime.fromtimestamp(info.st_mtime, UTC) > cutoff:
        return "RAW_FILE_MTIME_RECENT", ref_ids
    return None, ref_ids


def _item(row, reason=None, reference_ids=None):
    result = {
        "raw_file_id": row.id,
        "raw_path": row.raw_path,
        "sha256": row.sha256,
        "byte_size": row.byte_size,
        "collected_at": row.collected_at,
    }
    if reference_ids is not None:
        result["reference_ids"] = reference_ids
    if reason is not None:
        result["reason"] = reason
    return result


def _preview_page(session, *, root: Path, cutoff: datetime, retention_days: int, limit: int, after=None):
    with session.no_autoflush:
        _require_schema(session)
        total = session.scalar(
            select(func.count()).select_from(RawSourceFile).where(
                RawSourceFile.storage_root == str(root), RawSourceFile.deleted_at.is_(None)
            )
        )
        query = select(RawSourceFile).where(
            RawSourceFile.storage_root == str(root), RawSourceFile.deleted_at.is_(None)
        )
        if after is not None:
            collected_at, file_id = after
            query = query.where(
                or_(
                    RawSourceFile.collected_at > collected_at,
                    and_(RawSourceFile.collected_at == collected_at, RawSourceFile.id > file_id),
                )
            )
        page = list(
            session.scalars(query.order_by(RawSourceFile.collected_at, RawSourceFile.id).limit(limit + 1))
        )
        has_more = len(page) > limit
        rows = page[:limit]
        candidates, blocked, seen = [], [], set()
        for row in rows:
            identity = (row.raw_path, row.sha256)
            if identity in seen:
                continue
            seen.add(identity)
            reason, references = _evaluate(session, row, root, cutoff)
            target = blocked if reason else candidates
            target.append(_item(row, reason, references))
    result = {
        "storage_root": str(root),
        "retention_days": retention_days,
        "cutoff": cutoff,
        "total": int(total or 0),
        "total_count": int(total or 0),
        "inspected_count": len(rows),
        "candidate_count": len(candidates),
        "blocked_count": len(blocked),
        "candidates": candidates,
        "blocked": blocked,
    }
    result["has_more"] = has_more
    result["next_cursor"] = (
        (rows[-1].collected_at, rows[-1].id) if rows and has_more else None
    )
    return result


def preview_raw_retention(session, *, storage_root, now=None, retention_days=30, limit=100):
    """Return the oldest bounded page without mutating data or scan state."""
    _bounds(retention_days, limit)
    instant = _now(now)
    cutoff = instant - timedelta(days=retention_days)
    root = canonical_storage_root(storage_root)
    return _preview_page(
        session, root=root, cutoff=cutoff, retention_days=retention_days, limit=limit
    )


def _parent_fd(root: Path, relative: PurePosixPath) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.open(root, flags)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


def _stat_identity(info) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _stage(root: Path, source: PurePosixPath, staged: PurePosixPath, expected_hash: str, expected_size: int) -> None:
    digest, size, original = file_identity(root, source)
    if digest != expected_hash or size != expected_size:
        raise RawSourceError("RAW_FILE_HASH_CHANGED")
    parent = _parent_fd(root, source)
    try:
        os.rename(source.name, staged.name, src_dir_fd=parent, dst_dir_fd=parent)
        moved = os.stat(staged.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(moved.st_mode) or _stat_identity(moved) != _stat_identity(original):
            try:
                os.rename(staged.name, source.name, src_dir_fd=parent, dst_dir_fd=parent)
            except OSError:
                pass
            raise RawSourceError("RAW_FILE_TOCTOU_BLOCKED")
    except FileExistsError:
        raise RawSourceError("RAW_RETENTION_STAGE_EXISTS")
    except RawSourceError:
        raise
    except OSError:
        raise RawSourceError("RAW_RETENTION_STAGE_FAILED")
    finally:
        os.close(parent)


def _restore(
    root: Path,
    source: PurePosixPath,
    staged: PurePosixPath,
    expected_hash: str,
    expected_size: int,
) -> bool:
    """Restore only the exact staged inode and never replace a new source."""
    unlinking = staged.with_name(staged.name + ".unlinking")
    staged_present = os.path.lexists(root / staged.as_posix())
    unlinking_present = os.path.lexists(root / unlinking.as_posix())
    if not staged_present and not unlinking_present:
        return False
    target = staged if staged_present else unlinking
    digest, size, staged_info = file_identity(root, target)
    if digest != expected_hash or size != expected_size:
        raise RawSourceError("RAW_RETENTION_STAGE_CHANGED")
    parent = _parent_fd(root, source)
    try:
        try:
            os.stat(source.name, dir_fd=parent, follow_symlinks=False)
            return False
        except FileNotFoundError:
            current = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode) or _stat_identity(current) != _stat_identity(staged_info):
                raise RawSourceError("RAW_RETENTION_STAGE_CHANGED")
            # Hard-link with no replacement gives us an atomic "restore only if
            # absent" primitive that os.rename does not provide.
            try:
                os.link(
                    target.name,
                    source.name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileExistsError:
                return False
            restored = os.stat(source.name, dir_fd=parent, follow_symlinks=False)
            if _stat_identity(restored) != _stat_identity(staged_info):
                latest = os.stat(source.name, dir_fd=parent, follow_symlinks=False)
                if _stat_identity(latest) == _stat_identity(restored):
                    os.unlink(source.name, dir_fd=parent)
                raise RawSourceError("RAW_FILE_TOCTOU_BLOCKED")
            current = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
            if _stat_identity(current) != _stat_identity(staged_info):
                raise RawSourceError("RAW_RETENTION_STAGE_CHANGED")
            os.unlink(target.name, dir_fd=parent)
            return True
    except RawSourceError:
        raise
    except OSError:
        raise RawSourceError("RAW_RETENTION_RESTORE_FAILED")
    finally:
        os.close(parent)


def _unlink_stage(root: Path, staged: PurePosixPath, expected_hash: str, expected_size: int) -> None:
    unlinking = staged.with_name(staged.name + ".unlinking")
    staged_full = root / staged.as_posix()
    unlinking_full = root / unlinking.as_posix()
    target = unlinking if os.path.lexists(unlinking_full) and not os.path.lexists(staged_full) else staged
    digest, size, read_info = file_identity(root, target)
    if digest != expected_hash or size != expected_size:
        raise RawSourceError("RAW_RETENTION_STAGE_CHANGED")
    parent = _parent_fd(root, target)
    try:
        current = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or _stat_identity(current) != _stat_identity(read_info):
            raise RawSourceError("RAW_RETENTION_STAGE_CHANGED")
        if target == staged:
            try:
                os.stat(unlinking.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise RawSourceError("RAW_RETENTION_STAGE_EXISTS")
            os.rename(staged.name, unlinking.name, src_dir_fd=parent, dst_dir_fd=parent)
            moved = os.stat(unlinking.name, dir_fd=parent, follow_symlinks=False)
            if _stat_identity(moved) != _stat_identity(read_info):
                try:
                    os.stat(staged.name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    os.rename(unlinking.name, staged.name, src_dir_fd=parent, dst_dir_fd=parent)
                except OSError:
                    pass
                raise RawSourceError("RAW_RETENTION_STAGE_CHANGED")
        final = os.stat(unlinking.name, dir_fd=parent, follow_symlinks=False)
        if _stat_identity(final) != _stat_identity(read_info):
            raise RawSourceError("RAW_RETENTION_STAGE_CHANGED")
        os.unlink(unlinking.name, dir_fd=parent)
    except RawSourceError:
        raise
    except FileNotFoundError:
        # A prior executor may have completed the unlink after the staged commit.
        return
    except OSError:
        raise RawSourceError("RAW_RETENTION_UNLINK_FAILED")
    finally:
        os.close(parent)


def _staged_artifact_exists(root: Path, staged: PurePosixPath) -> bool:
    return os.path.lexists(root / staged.as_posix()) or os.path.lexists(
        root / (staged.as_posix() + ".unlinking")
    )


def _mark_deleted(session, event, when: datetime, error_code=None) -> None:
    session.execute(
        update(RawSourceFile)
        .where(
            RawSourceFile.storage_root == event.storage_root,
            RawSourceFile.raw_path == event.raw_path,
            RawSourceFile.sha256 == event.sha256,
            RawSourceFile.deleted_at.is_(None),
        )
        .values(state="deleted", deleted_at=when)
    )
    event.status = "deleted"
    event.completed_at = when
    event.error_code = error_code


def _release_event_claim(session, event) -> None:
    session.execute(
        update(RawSourceFile)
        .where(
            RawSourceFile.storage_root == event.storage_root,
            RawSourceFile.raw_path == event.raw_path,
            RawSourceFile.sha256 == event.sha256,
            RawSourceFile.state == "deleting",
            RawSourceFile.deleted_at.is_(None),
        )
        .values(state="loaded")
    )


def _event_owner_has_lease(session, event, when: datetime) -> bool:
    try:
        owner = session.get(TaskRun, UUID(event.task_run_id))
    except (TypeError, ValueError, AttributeError):
        owner = None
    return (
        owner is not None
        and owner.status in ACTIVE_TASK_STATES
        and when - event.intended_at < RETENTION_INTENT_LEASE
    )


def _recovery_metadata_error(session, row, event, root: Path, cutoff: datetime, reference_ids) -> str | None:
    if (
        row.storage_root != str(root)
        or row.raw_path != event.raw_path
        or row.sha256 != event.sha256
        or row.byte_size != event.byte_size
    ):
        return "RAW_RETENTION_EVENT_IDENTITY_MISMATCH"
    claimed = set(reference_ids)
    references = _physical_refs(session, row)
    if not references:
        return "RAW_METADATA_MISSING"
    if any(
        ref.state not in {"loaded", "deleting"}
        or (ref.state == "deleting" and ref.id not in claimed)
        for ref in references
    ):
        return "RAW_FILE_STATE_BLOCKED"
    if any(ref.collected_at > cutoff for ref in references):
        return "RETENTION_NOT_DUE"
    if any(_producer_active(session, ref.producer_run_id) for ref in references):
        return "PRODUCER_TASK_ACTIVE"
    for ref in references:
        error = _load_coverage_error(session, ref)
        if error:
            return error
    return _known_source_coverage_error(session, references)


def _reconcile_staged(session, root: Path, when: datetime, cutoff: datetime) -> int:
    reconciled = 0
    events = list(
        session.scalars(
            select(RawRetentionEvent).where(
                RawRetentionEvent.storage_root == str(root),
                RawRetentionEvent.status.in_(("intent", "staged")),
            )
        )
    )
    for event in events:
        # Another live executor owns every phase of the durable intent until its
        # lease expires.  In particular, a staged file is not permission for a
        # second executor to finish the first executor's unlink.
        if _event_owner_has_lease(session, event, when):
            continue
        try:
            source = normalized_raw_path(event.raw_path)
            staged = normalized_raw_path(event.staged_path)
        except RawSourceError as exc:
            event.status = "failed"
            event.error_code = str(exc)
            _release_event_claim(session, event)
            session.commit()
            reconciled += 1
            continue
        source_exists = os.path.lexists(root / source.as_posix())
        staged_exists = _staged_artifact_exists(root, staged)
        row = session.get(RawSourceFile, event.raw_file_id)
        if row is None:
            event.status = "failed"
            event.error_code = "RAW_METADATA_MISSING"
            session.commit()
            reconciled += 1
            continue
        references = _physical_refs(session, row)
        reference_ids = [ref.id for ref in references]
        if staged_exists and not source_exists:
            physical = staged
            if not os.path.lexists(root / staged.as_posix()):
                physical = staged.with_name(staged.name + ".unlinking")
            reason, _ = _evaluate(
                session,
                row,
                root,
                cutoff,
                claimed_ids=reference_ids,
                physical_path=physical,
            )
            if reason:
                event.status = "blocked"
                event.error_code = reason
                _restore(root, source, staged, event.sha256, event.byte_size)
                _release_event_claim(session, event)
            else:
                _unlink_stage(root, staged, event.sha256, event.byte_size)
                _mark_deleted(session, event, when, "RAW_RETENTION_RECONCILED")
            session.commit()
            reconciled += 1
        elif not staged_exists and not source_exists:
            # Only a durable staged transition proves that this executor had
            # moved the exact source and may have unlinked it before crashing.
            metadata_error = _recovery_metadata_error(
                session, row, event, root, cutoff, reference_ids
            )
            if event.status == "staged" and event.staged_at is not None and metadata_error is None:
                _mark_deleted(session, event, when, "RAW_RETENTION_RECONCILED_MISSING")
            else:
                event.status = "blocked" if metadata_error else "failed"
                event.error_code = metadata_error or "RAW_RETENTION_MISSING_UNVERIFIED"
                _release_event_claim(session, event)
            session.commit()
            reconciled += 1
        elif source_exists and staged_exists:
            event.status = "blocked"
            event.error_code = "RAW_RETENTION_SOURCE_REAPPEARED"
            _release_event_claim(session, event)
            session.commit()
            reconciled += 1
        else:
            reason, _ = _evaluate(
                session,
                row,
                root,
                cutoff,
                claimed_ids=reference_ids,
            )
            event.status = "blocked" if reason else "failed"
            event.error_code = reason or "RAW_RETENTION_INTENT_EXPIRED"
            _release_event_claim(session, event)
            session.commit()
            reconciled += 1
    return reconciled


def apply_raw_retention(session_factory, *, storage_root, now=None, retention_days=30, limit=100):
    """Apply retention with committed intent and a recoverable same-directory stage."""
    _bounds(retention_days, limit)
    instant = _now(now)
    cutoff = instant - timedelta(days=retention_days)
    root = canonical_storage_root(storage_root)
    run_id, step_id = uuid4(), uuid4()
    result = {
        "storage_root": str(root),
        "retention_days": retention_days,
        "cutoff": cutoff,
        "task_run_id": str(run_id),
        "candidate_count": 0,
        "deleted_count": 0,
        "blocked_count": 0,
        "reconciled_count": 0,
        "deleted": [],
        "blocked": [],
    }
    with session_factory() as session:
        _require_schema(session)
        task = TaskRun(
            id=run_id,
            name="raw-source-retention",
            task_type="raw_retention",
            status=TaskStatus.running,
            current_stage="retention",
            started_at=instant,
        )
        step = TaskStep(
            id=step_id,
            task_run_id=run_id,
            name="prune_raw_sources",
            stage="retention",
            task_kind="raw_retention",
            status=StepStatus.running,
            started_at=instant,
        )
        session.add(task)
        session.flush([task])
        session.add(step)
        session.commit()
        try:
            result["reconciled_count"] = _reconcile_staged(session, root, instant, cutoff)
            scan = session.get(RawRetentionScan, str(root))
            scan_after = None
            if scan is not None and scan.last_collected_at is not None and scan.last_file_id is not None:
                scan_after = (scan.last_collected_at, scan.last_file_id)
            preview = _preview_page(
                session,
                root=root,
                cutoff=cutoff,
                retention_days=retention_days,
                limit=limit,
                after=scan_after,
            )
            scan_wrapped = False
            if scan_after is not None and preview["inspected_count"] == 0 and preview["total_count"]:
                preview = _preview_page(
                    session,
                    root=root,
                    cutoff=cutoff,
                    retention_days=retention_days,
                    limit=limit,
                )
                scan_wrapped = True
            result["scan_started_after"] = scan_after
            result["scan_wrapped"] = scan_wrapped
            result["scan_has_more"] = preview["has_more"]
            result["candidate_count"] = preview["candidate_count"]
            result["blocked_count"] = preview["blocked_count"]
            result["blocked"].extend(preview["blocked"])
            for candidate in preview["candidates"]:
                row = session.get(RawSourceFile, candidate["raw_file_id"])
                reason, reference_ids = _evaluate(session, row, root, cutoff)
                if reason:
                    result["blocked_count"] += 1
                    result["blocked"].append(_item(row, reason, reference_ids))
                    continue
                claim = session.execute(
                    update(RawSourceFile)
                    .where(RawSourceFile.id.in_(reference_ids), RawSourceFile.state == "loaded")
                    .values(state="deleting")
                )
                if claim.rowcount != len(reference_ids):
                    session.rollback()
                    result["blocked_count"] += 1
                    result["blocked"].append(_item(row, "RAW_RETENTION_CONCURRENT", reference_ids))
                    continue
                event_id = str(uuid4())
                relative = normalized_raw_path(row.raw_path)
                staged = relative.parent / (f".{relative.name}.raw-retention-{event_id}")
                event = RawRetentionEvent(
                    id=event_id,
                    raw_file_id=row.id,
                    action="delete",
                    status="intent",
                    task_run_id=str(run_id),
                    task_step_id=str(step_id),
                    storage_root=str(root),
                    raw_path=row.raw_path,
                    staged_path=staged.as_posix(),
                    sha256=row.sha256,
                    byte_size=row.byte_size,
                    intended_at=instant,
                )
                session.add(event)
                # Intent and claim must be durable before touching the filesystem.
                session.commit()
                reason, _ = _evaluate(session, row, root, cutoff, claimed_ids=reference_ids)
                if reason:
                    event.status = "blocked"
                    event.error_code = reason
                    session.execute(
                        update(RawSourceFile).where(RawSourceFile.id.in_(reference_ids)).values(state="loaded")
                    )
                    session.commit()
                    result["blocked_count"] += 1
                    result["blocked"].append(_item(row, reason, reference_ids))
                    continue
                try:
                    _stage(root, relative, staged, row.sha256, row.byte_size)
                    event.status = "staged"
                    event.staged_at = instant
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                        _restore(root, relative, staged, row.sha256, row.byte_size)
                        raise
                    _unlink_stage(root, staged, row.sha256, row.byte_size)
                    _mark_deleted(session, event, instant)
                    session.commit()
                    result["deleted_count"] += 1
                    result["deleted"].append(_item(row, reference_ids=reference_ids))
                except RawSourceError as exc:
                    session.rollback()
                    _restore(root, relative, staged, row.sha256, row.byte_size)
                    event = session.get(RawRetentionEvent, event_id)
                    if event is not None and event.status != "deleted":
                        event.status = "failed"
                        event.error_code = str(exc)
                        session.execute(
                            update(RawSourceFile)
                            .where(RawSourceFile.id.in_(reference_ids), RawSourceFile.deleted_at.is_(None))
                            .values(state="loaded")
                        )
                        session.commit()
                    result["blocked_count"] += 1
                    result["blocked"].append(_item(row, str(exc), reference_ids))
                except Exception:
                    # A failed staged-state commit is reversible and must not leave
                    # the source claimed. If unlink already happened, retain the
                    # durable staged event for the next invocation to reconcile.
                    session.rollback()
                    source_exists = os.path.lexists(root / relative.as_posix())
                    staged_exists = _staged_artifact_exists(root, staged)
                    if source_exists or staged_exists:
                        if os.path.lexists(root / staged.as_posix()) and not source_exists:
                            _restore(root, relative, staged, row.sha256, row.byte_size)
                            source_exists = os.path.lexists(root / relative.as_posix())
                        if source_exists:
                            event = session.get(RawRetentionEvent, event_id)
                            if event is not None:
                                event.status = "failed"
                                event.error_code = "RAW_RETENTION_DATABASE_FAILED"
                                session.execute(
                                    update(RawSourceFile)
                                    .where(
                                        RawSourceFile.id.in_(reference_ids), RawSourceFile.deleted_at.is_(None)
                                    )
                                    .values(state="loaded")
                                )
                                session.commit()
                    raise
            scan = session.get(RawRetentionScan, str(root))
            if scan is None:
                scan = RawRetentionScan(storage_root=str(root))
                session.add(scan)
            next_cursor = preview["next_cursor"]
            scan.last_collected_at = next_cursor[0] if next_cursor else None
            scan.last_file_id = next_cursor[1] if next_cursor else None
            scan.updated_at = instant
            result["scan_next_cursor"] = next_cursor
            task = session.get(TaskRun, run_id)
            step = session.get(TaskStep, step_id)
            task.status = TaskStatus.partial_success if result["blocked_count"] else TaskStatus.success
            task.progress = 1.0
            task.current_stage = "complete"
            task.ended_at = instant
            step.status = StepStatus.success
            step.finished_at = instant
            session.commit()
            return result
        except Exception:
            session.rollback()
            try:
                task = session.get(TaskRun, run_id)
                step = session.get(TaskStep, step_id)
                if task is not None:
                    task.status = TaskStatus.failed
                    task.ended_at = instant
                    task.error_summary = "RAW_RETENTION_FAILED"
                if step is not None:
                    step.status = StepStatus.failed
                    step.finished_at = instant
                    step.error = "RAW_RETENTION_FAILED"
                session.commit()
            except Exception:
                session.rollback()
            raise
