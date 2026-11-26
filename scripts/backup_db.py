"""Back up the NMS database (all companies, tickets, history, activity log) safely while it runs.

    python scripts/backup_db.py                       # data/nms.sqlite -> backups/, keep newest 30
    python scripts/backup_db.py --db data/demo.sqlite --keep 7
    python scripts/backup_db.py --restore backups/nms-20261126T020000Z.sqlite --db data/nms.sqlite

Uses SQLite's online backup API, so it is consistent even while the API is writing.
Every copy is checked with PRAGMA integrity_check; a bad copy is deleted and the script fails.
Restore refuses to overwrite an existing database unless it first saves that database as
<db>.before-restore-<time>, so a restore can itself be undone. Schedule it daily
(the API does this itself while NMS_AUTO_SYNC_SECONDS > 0; see NMS_BACKUP_HOURS) and copy backups/ off the machine. See docs/ticketing-and-data.md.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integration-api"))

from app.backup import BackupError, backup, restore  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "nms.sqlite")
    ap.add_argument("--out", type=Path, default=ROOT / "backups")
    ap.add_argument("--keep", type=int, default=30, help="how many backups to keep (0 = keep all)")
    ap.add_argument("--restore", type=Path, help="restore this backup file into --db")
    a = ap.parse_args()
    try:
        run(a)
    except BackupError as exc:
        raise SystemExit(str(exc))


def run(a) -> None:
    if a.restore:
        saved = restore(a.restore, a.db)
        print(f"Restored {a.restore} into {a.db}." + (f" Previous database saved as {saved}." if saved else ""))
        print("Restart the API so it uses the restored data.")
    else:
        print(f"Backup written: {backup(a.db, a.out, a.keep)}")


if __name__ == "__main__":
    sys.exit(main())
