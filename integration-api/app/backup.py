"""Consistent SQLite backups of the NMS database (used by the API's daily backup and by
scripts/backup_db.py). Uses SQLite's online backup API, so a copy is consistent even while the
API is writing. Every copy is checked with PRAGMA integrity_check; a bad copy is deleted."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class BackupError(RuntimeError):
    pass


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def copy(src: Path, dst: Path) -> None:
    s, d = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        s.close()
        d.close()
    d = sqlite3.connect(dst)
    try:
        ok = d.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        d.close()
    if ok != "ok":
        dst.unlink(missing_ok=True)
        raise BackupError(f"Backup failed integrity check: {ok}")


def backup(db: Path, out: Path, keep: int) -> Path:
    if not db.exists():
        raise BackupError(f"No database at {db}")
    out.mkdir(parents=True, exist_ok=True)
    dst = out / f"{db.stem}-{stamp()}.sqlite"
    copy(db, dst)
    olds = sorted(out.glob(f"{db.stem}-*.sqlite"))
    for old in olds[:-keep] if keep > 0 else []:
        old.unlink()
    return dst


def latest(db: Path, out: Path) -> datetime | None:
    files = sorted(out.glob(f"{db.stem}-*.sqlite")) if out.exists() else []
    if not files:
        return None
    try:
        return datetime.strptime(files[-1].stem.rsplit("-", 1)[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def restore(src: Path, db: Path) -> Path | None:
    if not src.exists():
        raise BackupError(f"No backup at {src}")
    saved = None
    if db.exists():
        saved = db.with_name(f"{db.name}.before-restore-{stamp()}")
        copy(db, saved)
    copy(src, db)
    return saved
