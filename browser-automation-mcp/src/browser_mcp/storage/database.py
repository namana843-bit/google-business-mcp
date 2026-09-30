"""SQLite storage for audit logging, approval tracking, and profile metadata."""

import json
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from browser_mcp.models.schemas import ApprovalRequest, ApprovalStatus
from browser_mcp.utils.logging import get_logger

logger = get_logger("storage")

# Relative paths anchor to the project root rather than the process CWD, so the
# approvals database is the same file no matter which directory an MCP client
# happens to launch the server from. src/browser_mcp/storage/database.py sits
# three levels below the root.
_PACKAGE_ROOT = Path(__file__).resolve().parents[3]

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        action_type TEXT NOT NULL,
        description TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        resolved_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        action TEXT NOT NULL,
        target_url TEXT,
        profile TEXT,
        status TEXT NOT NULL,
        details_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS profiles (
        name TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        last_used TEXT NOT NULL,
        metadata_json TEXT
    )
    """,
    # Columns the hot paths actually filter on.
    "CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp DESC)",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _to_request(row: sqlite3.Row) -> ApprovalRequest:
    """Maps an `approvals` row onto its model."""
    return ApprovalRequest(
        id=row["id"],
        action_type=row["action_type"],
        description=row["description"],
        details=json.loads(row["payload_json"] or "{}"),
        status=ApprovalStatus(row["status"]),
        created_at=row["created_at"],
        resolved_at=row["resolved_at"],
    )


class DatabaseManager:
    """Manages lightweight local SQLite persistence for approvals and audit events."""

    def __init__(self, db_path: Optional[str] = None):
        raw = db_path or os.getenv("BROWSER_MCP_DB_PATH", "./browser_mcp.db")
        candidate = Path(raw.strip().strip('"').strip("'")).expanduser()
        if not candidate.is_absolute():
            candidate = (_PACKAGE_ROOT / candidate).resolve()
        self.db_path = str(candidate)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Yields a configured connection and *always* closes it.

        `with sqlite3.connect(...)` only scopes a transaction; it never closes
        the handle, which leaks file descriptors until the database reports
        "database is locked" under sustained use.
        """
        conn = self._get_connection()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Returns a raw connection. Prefer the _connection() context manager."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connection() as conn:
            for statement in _SCHEMA:
                conn.execute(statement)
            conn.commit()
        logger.debug(f"Database initialized at {self.db_path}")

    # --- Approval Methods ---

    def create_approval_request(
        self,
        action_type: str,
        description: str,
        details: dict[str, Any],
    ) -> ApprovalRequest:
        now = _utc_now()
        req = ApprovalRequest(
            id=f"appr_{uuid.uuid4().hex[:10]}",
            action_type=action_type,
            description=description,
            details=details,
            created_at=now,
        )
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO approvals (id, action_type, description, payload_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    req.id,
                    req.action_type,
                    req.description,
                    json.dumps(details),
                    req.status.value,
                    now,
                ),
            )
            conn.commit()
        return req

    def get_approval_request(self, approval_id: str) -> Optional[ApprovalRequest]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        return _to_request(row) if row else None

    def list_pending_approvals(self) -> list[ApprovalRequest]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE status = ? ORDER BY created_at DESC",
                (ApprovalStatus.PENDING.value,),
            ).fetchall()
        return [_to_request(row) for row in rows]

    def resolve_approval_request(
        self, approval_id: str, approved: bool
    ) -> Optional[ApprovalRequest]:
        """Approves or rejects a PENDING request.

        Returns None if the request is missing or already resolved, so a
        CONSUMED/decided approval cannot be flipped after the fact.
        """
        req = self.get_approval_request(approval_id)
        if not req:
            return None
        if req.status != ApprovalStatus.PENDING:
            logger.warning(
                f"Refusing to re-resolve approval '{approval_id}' "
                f"already in state {req.status.value}."
            )
            return None

        req.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        resolved_at = _utc_now()
        with self._connection() as conn:
            # Guarding on status in the WHERE clause means a concurrent resolver
            # cannot double-apply the same decision.
            cursor = conn.execute(
                "UPDATE approvals SET status = ?, resolved_at = ? "
                "WHERE id = ? AND status = ?",
                (
                    req.status.value,
                    resolved_at,
                    approval_id,
                    ApprovalStatus.PENDING.value,
                ),
            )
            if cursor.rowcount != 1:
                return None

        req.resolved_at = resolved_at
        return req

    def consume_approval_request(self, approval_id: str) -> bool:
        """Atomically marks an APPROVED request as CONSUMED.

        Returns True exactly once per approval id; every later call returns
        False, which prevents a single approval from being replayed.
        """
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE approvals SET status = ? WHERE id = ? AND status = ?",
                (
                    ApprovalStatus.CONSUMED.value,
                    approval_id,
                    ApprovalStatus.APPROVED.value,
                ),
            )
            return cursor.rowcount == 1

    # --- Audit Log Methods ---

    def log_action(
        self,
        action: str,
        target_url: Optional[str] = None,
        profile: Optional[str] = None,
        status: str = "SUCCESS",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Records an audit event. Never raises: losing a log line must not
        abort the browser action that produced it."""
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_logs
                        (timestamp, action, target_url, profile, status, details_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _utc_now(),
                        action,
                        target_url,
                        profile,
                        status,
                        json.dumps(details or {}),
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to record audit log: {e}")

    # --- Profile Metadata Methods ---

    def touch_profile(
        self, name: str, metadata: Optional[dict[str, Any]] = None
    ) -> None:
        now = _utc_now()
        payload = json.dumps(metadata or {})
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name FROM profiles WHERE name = ?", (name,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE profiles SET last_used = ?, metadata_json = ? WHERE name = ?",
                    (now, payload, name),
                )
            else:
                conn.execute(
                    "INSERT INTO profiles (name, created_at, last_used, metadata_json) "
                    "VALUES (?, ?, ?, ?)",
                    (name, now, now, payload),
                )
            conn.commit()
