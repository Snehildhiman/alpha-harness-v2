"""Backups of what cannot be re-synced, restored by merging, and made on a schedule.

A backup zips the vault (every Alpha and its daily PnL), the crowd history, the trained
models and the app's database. The catalog's fields are left out (a sync rebuilds them), and
so is the key that unlocks saved credentials, so a backup alone reveals no password or key.

Restoring **merges**: every Alpha, PnL day and crowd snapshot in the backup that is missing
here is added back, and nothing newer is overwritten or deleted. The models are restored only
when asked, or when none are trained here. The app's database (tasks, settings, prompts) is
restored only when asked, and only at the next start, before anything opens it: replacing it
under a running app would tear it. The one it replaces is kept beside it.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from .config import Settings

log = structlog.get_logger(__name__)

#: Catalog tables a sync rebuilds: not worth the space.
RESYNCABLE = frozenset({"data_field", "data_set", "data_category"})
#: Backups kept; the oldest go first.
KEEP = 10
#: How often the schedule looks whether a backup is due.
CHECK_SECONDS = 3600
#: Written beside the database by a restore, swapped in at the next start.
PENDING = "harness-restore-pending.db"

_lock = asyncio.Lock()


def folder(settings: Settings) -> Path:
    return settings.data_dir / "backups" / "full"


def listed(settings: Settings) -> list[tuple[Path, datetime]]:
    where = folder(settings)
    if not where.exists():
        return []
    found = [
        (p, datetime.fromtimestamp(p.stat().st_mtime, UTC)) for p in where.glob("backup-*.zip")
    ]
    return sorted(found, key=lambda pw: pw[1], reverse=True)


def path_of(settings: Settings, name: str) -> Path | None:
    """The backup called ``name``, or ``None`` for anything that is not one of them."""
    path = folder(settings) / name
    if (
        not name.startswith("backup-")
        or not name.endswith(".zip")
        or path.parent != folder(settings)
    ):
        return None
    return path if path.exists() else None


def busy() -> bool:
    return _lock.locked()


async def create(state: Any) -> Path:
    """Zip what cannot be re-synced. Raises ``RuntimeError`` while another is being made."""
    if _lock.locked():
        raise RuntimeError("A backup is being made already.")
    async with _lock:
        settings = state.settings
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        where = folder(settings)
        where.mkdir(parents=True, exist_ok=True)
        target = where / f"backup-{stamp}.zip"
        with tempfile.TemporaryDirectory(dir=where) as work:
            staging = Path(work)
            for table in await _tables(state):
                if table in RESYNCABLE:
                    continue
                out = staging / f"{table}.parquet"
                await state.catalog.execute(f"COPY {table} TO '{out.as_posix()}' (FORMAT parquet)")
            await asyncio.to_thread(_copy_sqlite, settings.sqlite_path, staging / "harness.db")
            await asyncio.to_thread(_zip, staging, settings.data_dir / "models", target)
        for old, _ in listed(settings)[KEEP:]:
            old.unlink(missing_ok=True)
        log.info("backup.made", path=str(target), bytes=target.stat().st_size)
        return target


async def _tables(state: Any) -> list[str]:
    return [
        str(r["table_name"])
        for r in await state.catalog.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
        )
    ]


def _copy_sqlite(source: Path, target: Path) -> None:
    """SQLite's backup API, never a file copy, which can tear a database in use."""
    with (
        contextlib.closing(sqlite3.connect(source)) as src,
        contextlib.closing(sqlite3.connect(target)) as dst,
    ):
        src.backup(dst)


def _zip(staging: Path, models: Path, target: Path) -> None:
    partial = target.with_suffix(".partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for path in sorted(staging.iterdir()):
            out.write(path, f"vault/{path.name}" if path.suffix == ".parquet" else path.name)
        if models.exists():
            for path in sorted(models.rglob("*")):
                if path.is_file():
                    out.write(path, f"models/{path.relative_to(models).as_posix()}")
        out.writestr(
            "README.txt",
            "Alpha Harness backup. Restore it from Health and Backup.\n"
            "vault/*.parquet: your Alphas, their daily PnL and the crowd history.\n"
            "harness.db: tasks, trials, settings (saved credentials stay locked: their key is "
            "not in this file).\nmodels/: the trained models in use.\n",
        )
    partial.replace(target)


async def restore(
    state: Any, path: Path, *, models: bool = False, database: bool = False
) -> dict[str, Any]:
    """Merge a backup back in. Returns what was added, per table."""
    if _lock.locked():
        raise RuntimeError("A backup is being made or restored already.")
    async with _lock:
        settings = state.settings
        added: dict[str, int] = {}
        with tempfile.TemporaryDirectory(dir=folder(settings)) as work:
            staging = Path(work)
            await asyncio.to_thread(_unzip, path, staging)
            present = set(await _tables(state))
            for parquet in sorted((staging / "vault").glob("*.parquet")):
                table = parquet.stem
                if table not in present or table in RESYNCABLE:
                    continue
                before = int(await state.catalog.scalar(f"SELECT count(*) FROM {table}") or 0)  # noqa: S608
                await state.catalog.execute(
                    f"INSERT OR IGNORE INTO {table} BY NAME "  # noqa: S608
                    f"SELECT * FROM read_parquet('{parquet.as_posix()}')"
                )
                after = int(await state.catalog.scalar(f"SELECT count(*) FROM {table}") or 0)  # noqa: S608
                added[table] = after - before
            restored_models = False
            backed = staging / "models"
            if backed.exists() and (models or await state.predictors.current() is None):
                await asyncio.to_thread(_swap_models, backed, settings.data_dir / "models")
                state.predictors.models, state.predictors._loaded = None, False
                restored_models = True
            staged_database = False
            if database and (staging / "harness.db").exists():
                shutil.copy2(staging / "harness.db", settings.data_dir / PENDING)
                staged_database = True
        log.info("backup.restored", path=str(path), added=added)
        return {"added": added, "models": restored_models, "database": staged_database}


def _unzip(path: Path, target: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            # Only the names a backup writes: nothing may land outside ``target``.
            name = Path(member.filename)
            if name.is_absolute() or ".." in name.parts:
                continue
            archive.extract(member, target)


def _swap_models(source: Path, target: Path) -> None:
    staging = Path(tempfile.mkdtemp(prefix="models-", dir=target.parent))
    shutil.copytree(source, staging, dirs_exist_ok=True)
    old = target.with_name(f"models-before-restore-{datetime.now(UTC):%Y%m%d%H%M%S}")
    if target.exists():
        target.rename(old)
    staging.rename(target)


def apply_pending(settings: Settings) -> bool:
    """At start, before the database opens: swap in a database a restore left waiting."""
    pending = settings.data_dir / PENDING
    if not pending.exists():
        return False
    current = settings.sqlite_path
    if current.exists():
        keep = (
            folder(settings).parent / f"harness-before-restore-{datetime.now(UTC):%Y%m%d%H%M%S}.db"
        )
        keep.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(current, keep)
        for extra in ("-wal", "-shm"):
            Path(f"{current}{extra}").unlink(missing_ok=True)
    shutil.move(pending, current)
    log.info("backup.database_restored")
    return True


def due(settings: Settings, every_days: int) -> bool:
    if every_days <= 0:
        return False
    found = listed(settings)
    return not found or datetime.now(UTC) - found[0][1] >= timedelta(days=every_days)


async def schedule(state: Any) -> None:
    """Every hour: a backup when the last is older than Settings' period."""
    from . import preferences

    while True:
        await asyncio.sleep(CHECK_SECONDS)
        try:
            every = (await preferences.load(state.db)).auto_backup_days
            if due(state.settings, every) and not busy():
                await create(state)
        except Exception:
            log.warning("backup.scheduled_failed", exc_info=True)
