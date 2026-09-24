"""Prepare error/stale rows in a disposable Gate E browser-test database only."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: e2e_mark_calendar_state.py DB_PATH CALENDAR_ID stale|error")
    path = Path(sys.argv[1]).resolve(strict=True)
    calendar_id, requested = sys.argv[2:]
    temp_root = Path(tempfile.gettempdir()).resolve()
    if (
        not path.is_file()
        or path.name != "memory.sqlite3"
        or path.parent.parent != temp_root
        or not path.parent.name.startswith("jarvis-gate-e2e-")
    ):
        raise SystemExit("refusing to touch a database outside the disposable Gate E test directory")
    if not calendar_id.startswith("sim_calendar_") or requested not in {"stale", "error"}:
        raise SystemExit("invalid synthetic state request")

    now = datetime.now(timezone.utc)
    if requested == "stale":
        last_success = now - timedelta(hours=25)
        last_attempt = last_success
        status, error_code = "simulated", None
    else:
        with sqlite3.connect(f"file:{path}?mode=rw", uri=True, timeout=2) as connection:
            row = connection.execute(
                "SELECT last_success_at FROM calendar_sync_states WHERE calendar_id = ?",
                (calendar_id,),
            ).fetchone()
        if row is None:
            raise SystemExit("synthetic calendar checkpoint does not exist")
        last_success = datetime.fromisoformat(row[0]) if row[0] else None
        last_attempt = now + timedelta(seconds=1)
        status, error_code = "error", "simulated_network"

    with sqlite3.connect(f"file:{path}?mode=rw", uri=True, timeout=2) as connection:
        cursor = connection.execute(
            "UPDATE calendar_sync_states SET sync_status = ?, last_success_at = ?, last_attempt_at = ?, error_code = ? WHERE calendar_id = ?",
            (status, last_success.isoformat() if last_success else None, last_attempt.isoformat(), error_code, calendar_id),
        )
        if cursor.rowcount != 1:
            raise SystemExit("synthetic calendar checkpoint does not exist")
        connection.commit()


if __name__ == "__main__":
    main()
