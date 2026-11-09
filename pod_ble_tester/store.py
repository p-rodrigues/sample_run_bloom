"""SQLite persistence for test results plus CSV export."""

from __future__ import annotations

import csv
import io
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from .ble import TestOutcome

CSV_COLUMNS = [
    "serial_number",
    "result",
    "tested_at",
    "connected_at",
    "duration_s",
    "ble_name",
    "address",
    "rssi",
    "error",
]


class ResultStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS results (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                serial_number TEXT    NOT NULL,
                result        TEXT    NOT NULL CHECK (result IN ('PASS', 'FAIL')),
                tested_at     TEXT    NOT NULL,
                connected_at  TEXT,
                duration_s    REAL,
                ble_name      TEXT,
                address       TEXT,
                rssi          INTEGER,
                error         TEXT
            )
            """
        )
        self._conn.commit()

    def add(self, outcome: TestOutcome) -> dict[str, Any]:
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO results
                    (serial_number, result, tested_at, connected_at, duration_s, ble_name, address, rssi, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.serial,
                    outcome.result,
                    outcome.tested_at,
                    outcome.connected_at,
                    outcome.duration_s,
                    outcome.ble_name,
                    outcome.address,
                    outcome.rssi,
                    outcome.error,
                ),
            )
            self._conn.commit()
            row_id = cur.lastrowid
        return self.get(row_id)  # type: ignore[return-value]

    def get(self, row_id: int) -> Optional[dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM results WHERE id = ?", (row_id,)).fetchone()
        return dict(row) if row else None

    def all(self, newest_first: bool = True) -> list[dict[str, Any]]:
        order = "DESC" if newest_first else "ASC"
        rows = self._conn.execute(f"SELECT * FROM results ORDER BY id {order}").fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> dict[str, int]:
        row = self._conn.execute(
            """
            SELECT COUNT(*)                                   AS total,
                   COALESCE(SUM(result = 'PASS'), 0)          AS passed,
                   COALESCE(SUM(result = 'FAIL'), 0)          AS failed
            FROM results
            """
        ).fetchone()
        return {"total": row["total"], "passed": row["passed"], "failed": row["failed"]}

    def to_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in self.all(newest_first=False):
            writer.writerow({k: ("" if row.get(k) is None else row[k]) for k in CSV_COLUMNS})
        return buf.getvalue()

    def close(self) -> None:
        self._conn.close()
