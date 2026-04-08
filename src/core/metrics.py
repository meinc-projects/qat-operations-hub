import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.logger import get_logger

logger = get_logger("hub.metrics")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS module_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_name TEXT NOT NULL,
    run_id TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    status TEXT NOT NULL,
    total_items INTEGER DEFAULT 0,
    processed INTEGER DEFAULT 0,
    succeeded INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS module_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    module_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    deal_id TEXT,
    deal_name TEXT,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    service TEXT NOT NULL,
    endpoint TEXT,
    tokens_used INTEGER,
    cost_estimate REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class MetricsCollector:
    """SQLite-backed metrics collector for module runs, events and API usage."""

    def __init__(self, data_dir: Path | None = None) -> None:
        if data_dir is None:
            data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = data_dir / "hub_metrics.db"
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(_SCHEMA)
        logger.info("Metrics database ready at %s", self.db_path)

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def start_run(self, module_name: str) -> str:
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO module_runs (module_name, run_id, started_at, status) VALUES (?, ?, ?, ?)",
                (module_name, run_id, now, "running"),
            )
        logger.info("Run started — module=%s, run_id=%s", module_name, run_id)
        return run_id

    def complete_run(
        self,
        run_id: str,
        status: str,
        summary: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        error_summary = json.dumps(summary) if summary else None
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE module_runs
                   SET completed_at = ?, status = ?, error_summary = ?,
                       total_items = COALESCE(total_items, 0),
                       processed  = COALESCE(processed, 0),
                       succeeded  = COALESCE(succeeded, 0),
                       failed     = COALESCE(failed, 0),
                       skipped    = COALESCE(skipped, 0)
                   WHERE run_id = ?""",
                (now, status, error_summary, run_id),
            )
        logger.info("Run completed — run_id=%s, status=%s", run_id, status)

    def update_run_counts(
        self,
        run_id: str,
        *,
        total_items: int | None = None,
        processed: int | None = None,
        succeeded: int | None = None,
        failed: int | None = None,
        skipped: int | None = None,
    ) -> None:
        sets: list[str] = []
        vals: list[Any] = []
        for col, val in [
            ("total_items", total_items),
            ("processed", processed),
            ("succeeded", succeeded),
            ("failed", failed),
            ("skipped", skipped),
        ]:
            if val is not None:
                sets.append(f"{col} = ?")
                vals.append(val)
        if not sets:
            return
        vals.append(run_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE module_runs SET {', '.join(sets)} WHERE run_id = ?", vals)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def record_event(
        self,
        run_id: str,
        module_name: str,
        event_type: str,
        deal_id: str | None = None,
        deal_name: str | None = None,
        details: dict | None = None,
    ) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO module_events (run_id, module_name, event_type, deal_id, deal_name, details) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, module_name, event_type, deal_id, deal_name, json.dumps(details) if details else None),
            )

    # ------------------------------------------------------------------
    # API usage
    # ------------------------------------------------------------------

    def record_api_usage(
        self,
        run_id: str,
        service: str,
        endpoint: str | None = None,
        tokens: int | None = None,
        cost: float | None = None,
    ) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO api_usage (run_id, service, endpoint, tokens_used, cost_estimate) VALUES (?, ?, ?, ?, ?)",
                (run_id, service, endpoint, tokens, cost),
            )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_module_status(self, module_name: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM module_runs WHERE module_name = ? ORDER BY started_at DESC LIMIT 1",
                (module_name,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_all_status(self) -> dict[str, dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM module_runs
                   WHERE id IN (SELECT MAX(id) FROM module_runs GROUP BY module_name)
                   ORDER BY module_name"""
            ).fetchall()
        return {row["module_name"]: dict(row) for row in rows}
