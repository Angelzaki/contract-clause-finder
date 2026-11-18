from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from contract_clauses.models import ScanReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    playbook TEXT NOT NULL,
    contracts TEXT NOT NULL,
    coverage_pct REAL NOT NULL,
    risk_adjusted_pct REAL NOT NULL,
    verdict TEXT NOT NULL,
    found INTEGER NOT NULL,
    partial INTEGER NOT NULL,
    missing INTEGER NOT NULL,
    critical_missing INTEGER NOT NULL,
    payload TEXT NOT NULL
)
"""


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def save_run(db_path: str | Path, report: ScanReport) -> int:
    with closing(_connect(db_path)) as conn, conn:
        cur = conn.execute(
            """
            INSERT INTO runs (created_at, label, playbook, contracts, coverage_pct, risk_adjusted_pct,
                              verdict, found, partial, missing, critical_missing, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.generated_at,
                report.label,
                report.playbook,
                ", ".join(report.contracts),
                report.coverage_pct,
                report.risk_adjusted_pct,
                report.verdict,
                report.counts["found"],
                report.counts["partial"],
                report.counts["missing"],
                len(report.critical_missing),
                json.dumps(report.to_dict(), ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)


def list_runs(db_path: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    if not Path(db_path).exists():
        return []
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, label, playbook, contracts, coverage_pct, risk_adjusted_pct, verdict,
                   found, partial, missing, critical_missing
            FROM runs ORDER BY id DESC LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_run(db_path: str | Path, run_id: int) -> dict[str, Any] | None:
    if not Path(db_path).exists():
        return None
    with closing(_connect(db_path)) as conn:
        row = conn.execute("SELECT payload FROM runs WHERE id = ?", (run_id,)).fetchone()
    return json.loads(row["payload"]) if row else None
