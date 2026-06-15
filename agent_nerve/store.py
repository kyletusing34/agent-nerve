from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

TASK_STATUSES = {"open", "in_progress", "blocked", "done"}
EVENT_KINDS = {"note", "progress", "blocked", "handoff", "done", "claim_acquired", "claim_released"}
VISIBILITY = {"shared", "internal"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class ClaimResult:
    ok: bool
    reason: str
    row: dict | None = None


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def init_db(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  namespace TEXT NOT NULL,
                  title TEXT NOT NULL,
                  status TEXT NOT NULL
                    CHECK (status IN ('open', 'in_progress', 'blocked', 'done')),
                  owner TEXT NOT NULL DEFAULT '',
                  summary TEXT NOT NULL DEFAULT '',
                  next_action TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  namespace TEXT NOT NULL,
                  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                  agent TEXT NOT NULL,
                  machine TEXT NOT NULL DEFAULT '',
                  kind TEXT NOT NULL
                    CHECK (kind IN ('note', 'progress', 'blocked', 'handoff', 'done', 'claim_acquired', 'claim_released')),
                  summary TEXT NOT NULL,
                  details TEXT NOT NULL DEFAULT '',
                  visibility TEXT NOT NULL DEFAULT 'shared'
                    CHECK (visibility IN ('shared', 'internal')),
                  metadata_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS claims (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  namespace TEXT NOT NULL,
                  resource TEXT NOT NULL,
                  agent TEXT NOT NULL,
                  machine TEXT NOT NULL DEFAULT '',
                  note TEXT NOT NULL DEFAULT '',
                  lease_expires_at TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(namespace, resource)
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_namespace_updated
                  ON tasks(namespace, updated_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_events_namespace_created
                  ON events(namespace, created_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_claims_namespace_resource
                  ON claims(namespace, resource);
                """
            )

    @staticmethod
    def rows(rows: list[sqlite3.Row]) -> list[dict]:
        return [dict(row) for row in rows]

    def list_tasks(self, namespace: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM tasks WHERE namespace = ? ORDER BY updated_at DESC, id DESC",
                (namespace,),
            ).fetchall()
        return self.rows(rows)

    def create_task(
        self,
        namespace: str,
        title: str,
        status: str = "open",
        owner: str = "",
        summary: str = "",
        next_action: str = "",
    ) -> dict:
        now = utc_now()
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO tasks (namespace, title, status, owner, summary, next_action, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (namespace, title, status, owner, summary, next_action, now, now),
            )
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def update_task(
        self,
        task_id: int,
        *,
        status: str | None = None,
        owner: str | None = None,
        summary: str | None = None,
        next_action: str | None = None,
    ) -> dict | None:
        updates: list[str] = []
        values: list[object] = []
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if owner is not None:
            updates.append("owner = ?")
            values.append(owner)
        if summary is not None:
            updates.append("summary = ?")
            values.append(summary)
        if next_action is not None:
            updates.append("next_action = ?")
            values.append(next_action)
        if not updates:
            return self.get_task(task_id)
        updates.append("updated_at = ?")
        values.append(utc_now())
        values.append(task_id)
        with self.connect() as db:
            db.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", values)
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def get_task(self, task_id: int) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list_events(self, namespace: str, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM events
                WHERE namespace = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (namespace, limit),
            ).fetchall()
        return self.rows(rows)

    def create_event(
        self,
        *,
        namespace: str,
        agent: str,
        kind: str,
        summary: str,
        details: str = "",
        visibility: str = "shared",
        machine: str = "",
        task_id: int | None = None,
        metadata: dict | list | None = None,
    ) -> dict:
        created_at = utc_now()
        payload = json.dumps(metadata or {}, separators=(",", ":"))
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO events (namespace, task_id, agent, machine, kind, summary, details, visibility, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (namespace, task_id, agent, machine, kind, summary, details, visibility, payload, created_at),
            )
            row = db.execute("SELECT * FROM events WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def list_claims(self, namespace: str) -> list[dict]:
        now = utc_now()
        with self.connect() as db:
            db.execute("DELETE FROM claims WHERE lease_expires_at <= ?", (now,))
            rows = db.execute(
                "SELECT * FROM claims WHERE namespace = ? ORDER BY updated_at DESC, id DESC",
                (namespace,),
            ).fetchall()
        return self.rows(rows)

    def acquire_claim(
        self,
        *,
        namespace: str,
        resource: str,
        agent: str,
        machine: str = "",
        note: str = "",
        ttl_seconds: int = 1800,
    ) -> ClaimResult:
        now = datetime.now(timezone.utc)
        lease_expires_at = (now + timedelta(seconds=max(ttl_seconds, 30))).isoformat()
        now_iso = now.isoformat()
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM claims WHERE namespace = ? AND resource = ?",
                (namespace, resource),
            ).fetchone()
            if row is None:
                cursor = db.execute(
                    """
                    INSERT INTO claims (namespace, resource, agent, machine, note, lease_expires_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (namespace, resource, agent, machine, note, lease_expires_at, now_iso, now_iso),
                )
                created = db.execute("SELECT * FROM claims WHERE id = ?", (cursor.lastrowid,)).fetchone()
                return ClaimResult(ok=True, reason="created", row=dict(created))

            current = dict(row)
            expired = parse_ts(current["lease_expires_at"]) <= now
            same_owner = current["agent"] == agent and current["machine"] == machine
            if expired or same_owner:
                db.execute(
                    """
                    UPDATE claims
                    SET agent = ?, machine = ?, note = ?, lease_expires_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (agent, machine, note, lease_expires_at, now_iso, current["id"]),
                )
                updated = db.execute("SELECT * FROM claims WHERE id = ?", (current["id"],)).fetchone()
                return ClaimResult(ok=True, reason="renewed" if same_owner else "reclaimed", row=dict(updated))
            return ClaimResult(ok=False, reason="already_claimed", row=current)

    def release_claim(self, claim_id: int) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
            if row is None:
                return None
            db.execute("DELETE FROM claims WHERE id = ?", (claim_id,))
        return dict(row)
