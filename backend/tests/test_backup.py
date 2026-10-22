"""Backups: made, merged back without replacing newer rows, and a database swapped at start."""

import asyncio
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alpha_harness import backup
from alpha_harness.config import Settings
from alpha_harness.db.duck import Catalog


class _Models:
    def __init__(self) -> None:
        self.models: Any = None
        self._loaded = True

    async def current(self) -> Any:
        return self.models


async def _state(tmp: Path) -> Any:
    settings = Settings(data_dir=tmp)
    catalog = Catalog(settings.duckdb_path)
    await catalog.open()
    with sqlite3.connect(settings.sqlite_path) as db:
        db.execute("CREATE TABLE t (x INTEGER)")
        db.execute("INSERT INTO t VALUES (1)")
    (tmp / "models").mkdir()
    (tmp / "models" / "report.json").write_text("{}")
    return SimpleNamespace(settings=settings, catalog=catalog, predictors=_Models())


async def _alpha(catalog: Catalog, alpha_id: str, sharpe: float) -> None:
    await catalog.execute(
        "INSERT OR REPLACE INTO alpha (alpha_id, sharpe) VALUES (?, ?)", [alpha_id, sharpe]
    )


def test_backup_round_trip(tmp_path: Path) -> None:
    async def go() -> None:
        state = await _state(tmp_path)
        await _alpha(state.catalog, "A1", 1.0)
        await _alpha(state.catalog, "A2", 2.0)
        path = await backup.create(state)
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
        assert {"vault/alpha.parquet", "harness.db", "models/report.json", "README.txt"} <= names
        assert not any(Path(n).name == "key" for n in names)
        assert "vault/data_field.parquet" not in names

        # A2 is lost and A1 changed since: restoring adds A2 and leaves A1 as it is now.
        await state.catalog.execute("DELETE FROM alpha WHERE alpha_id = 'A2'")
        await _alpha(state.catalog, "A1", 3.0)
        found = await backup.restore(state, path, database=True)
        assert found["added"]["alpha"] == 1
        rows = {
            r["alpha_id"]: r["sharpe"]
            for r in await state.catalog.query("SELECT alpha_id, sharpe FROM alpha")
        }
        assert rows == {"A1": 3.0, "A2": 2.0}
        # No models in use here, so the backup's come back.
        assert found["models"] is True
        assert found["database"] is True
        await state.catalog.close()

    asyncio.run(go())
    settings = Settings(data_dir=tmp_path)
    assert backup.apply_pending(settings)
    assert not (tmp_path / backup.PENDING).exists()
    with sqlite3.connect(settings.sqlite_path) as db:
        assert db.execute("SELECT x FROM t").fetchall() == [(1,)]
    assert list((tmp_path / "backups").glob("harness-before-restore-*.db"))


def test_due_follows_the_period(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    assert backup.due(settings, 7)
    assert not backup.due(settings, 0)
    where = backup.folder(settings)
    where.mkdir(parents=True)
    (where / "backup-20990101-000000.zip").write_bytes(b"")
    assert not backup.due(settings, 7)
    assert backup.path_of(settings, "../key") is None
