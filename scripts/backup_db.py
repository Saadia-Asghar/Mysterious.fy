"""Back up the NMS database (all companies, tickets, history, activity log) safely while it runs.

    python scripts/backup_db.py                       # data/nms.sqlite -> backups/, keep newest 30
    python scripts/backup_db.py --db data/demo.sqlite --keep 7
    python scripts/backup_db.py --restore backups/nms-20261126T020000Z.sqlite --db data/nms.sqlite

Uses SQLite's online backup API, so it is consistent even while the API is writing.
Every copy is checked with PRAGMA integrity_check; a bad copy is deleted and the script fails.
Restore refuses to overwrite an existing database unless it first saves that database as
<db>.before-restore-<time>, so a restore can itself be undone. Schedule it daily
(Windows Task Scheduler or cron) and copy backups/ off the machine. See docs/ticketing-and-data.md.
"""
import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def copy(src: Path, dst: Path) -> None:
    with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
        s.backup(d)
    with sqlite3.connect(dst) as d:
        ok = d.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        dst.unlink(missing_ok=True)
        raise SystemExit(f"Backup failed integrity check: {ok}")


def backup(db: Path, out: Path, keep: int) -> Path:
    if not db.exists():
        raise SystemExit(f"No database at {db}")
    out.mkdir(parents=True, exist_ok=True)
    dst = out / f"{db.stem}-{stamp()}.sqlite"
    copy(db, dst)
    olds = sorted(out.glob(f"{db.stem}-*.sqlite"))
    for old in olds[:-keep] if keep > 0 else []:
        old.unlink()
    return dst


def restore(src: Path, db: Path) -> Path | None:
    if not src.exists():
        raise SystemExit(f"No backup at {src}")
    saved = None
    if db.exists():
        saved = db.with_name(f"{db.name}.before-restore-{stamp()}")
        copy(db, saved)
    copy(src, db)
    return saved


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "nms.sqlite")
    ap.add_argument("--out", type=Path, default=ROOT / "backups")
    ap.add_argument("--keep", type=int, default=30, help="how many backups to keep (0 = keep all)")
    ap.add_argument("--restore", type=Path, help="restore this backup file into --db")
    a = ap.parse_args()
    if a.restore:
        saved = restore(a.restore, a.db)
        print(f"Restored {a.restore} into {a.db}." + (f" Previous database saved as {saved}." if saved else ""))
        print("Restart the API so it uses the restored data.")
    else:
        print(f"Backup written: {backup(a.db, a.out, a.keep)}")


if __name__ == "__main__":
    sys.exit(main())
