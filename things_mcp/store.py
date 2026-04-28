from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from .history import fold_history_items, todos as query_todos


def default_db_path() -> Path:
    configured = os.environ.get("THINGS_MCP_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "things-mcp" / "entities.sqlite"


class EntityStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path is not None else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @classmethod
    def from_env(cls) -> "EntityStore":
        return cls(default_db_path())

    def init_schema(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                create table if not exists sync_meta (
                    key text primary key,
                    value text not null
                )
                """
            )
            db.execute(
                """
                create table if not exists entities (
                    id text primary key,
                    entity_type text,
                    deleted integer not null default 0,
                    title text,
                    task_type integer,
                    status integer,
                    trashed integer not null default 0,
                    created_at real,
                    start_at real,
                    deadline_at real,
                    modified_at real,
                    raw_json text not null
                )
                """
            )
            added_date_column = self._ensure_column(db, "entities", "created_at", "real")
            added_date_column = self._ensure_column(db, "entities", "start_at", "real") or added_date_column
            added_date_column = self._ensure_column(db, "entities", "deadline_at", "real") or added_date_column
            if added_date_column:
                self._backfill_derived_columns(db)
            db.execute("create index if not exists idx_entities_kind on entities (entity_type, task_type)")
            db.execute("create index if not exists idx_entities_status on entities (deleted, trashed, status)")
            db.execute("create index if not exists idx_entities_created_at on entities (created_at)")
            db.execute("create index if not exists idx_entities_start_at on entities (start_at)")
            db.execute("create index if not exists idx_entities_deadline_at on entities (deadline_at)")

    def get_meta(self, key: str) -> str | None:
        with self._connect() as db:
            row = db.execute("select value from sync_meta where key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set_meta(self, key: str, value: str | int | float) -> None:
        with self._connect() as db:
            self._set_meta(db, key, value)

    def latest_item_index(self) -> int | None:
        value = self.get_meta("latest_item_index")
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def last_synced_at(self) -> float | None:
        value = self.get_meta("last_synced_at")
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def has_entities(self) -> bool:
        with self._connect() as db:
            row = db.execute("select 1 from entities limit 1").fetchone()
        return row is not None

    def load_state(self, entity_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
        with self._connect() as db:
            if entity_ids is None:
                rows = db.execute("select raw_json from entities").fetchall()
            elif not entity_ids:
                rows = []
            else:
                placeholders = ",".join("?" for _ in entity_ids)
                rows = db.execute(f"select raw_json from entities where id in ({placeholders})", entity_ids).fetchall()
        return {item["id"]: item for item in (json.loads(row["raw_json"]) for row in rows)}

    def list_todos(
        self,
        *,
        status: str = "open",
        project_id: str | None = None,
        area_id: str | None = None,
        tag_ids: list[str] | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
        start_from: int | None = None,
        start_to: int | None = None,
        deadline_from: int | None = None,
        deadline_to: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        candidate_ids = self._todo_candidate_ids(
            status=status,
            created_from=created_from,
            created_to=created_to,
            start_from=start_from,
            start_to=start_to,
            deadline_from=deadline_from,
            deadline_to=deadline_to,
        )
        state = self._load_state_for_todo_candidates(candidate_ids)
        return query_todos(
            state,
            status=status,
            project_id=project_id,
            area_id=area_id,
            tag_ids=tag_ids,
            created_from=created_from,
            created_to=created_to,
            start_from=start_from,
            start_to=start_to,
            deadline_from=deadline_from,
            deadline_to=deadline_to,
            limit=limit,
        )

    def _todo_candidate_ids(
        self,
        *,
        status: str,
        created_from: int | None,
        created_to: int | None,
        start_from: int | None,
        start_to: int | None,
        deadline_from: int | None,
        deadline_to: int | None,
    ) -> list[str]:
        clauses = ["entity_type = ?", "task_type = 0", *_status_clauses(status)]
        params: list[Any] = ["Task6"]
        if created_from is not None:
            clauses.append("created_at >= ?")
            params.append(created_from)
        if created_to is not None:
            clauses.append("created_at <= ?")
            params.append(created_to)
        if start_from is not None:
            clauses.append("start_at >= ?")
            params.append(start_from)
        if start_to is not None:
            clauses.append("start_at <= ?")
            params.append(start_to)
        if deadline_from is not None:
            clauses.append("deadline_at >= ?")
            params.append(deadline_from)
        if deadline_to is not None:
            clauses.append("deadline_at <= ?")
            params.append(deadline_to)

        where = " and ".join(clauses)
        with self._connect() as db:
            rows = db.execute(f"select id from entities where {where}", params).fetchall()
        return [str(row["id"]) for row in rows]

    def _load_state_for_todo_candidates(self, candidate_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not candidate_ids:
            return {}
        placeholders = ",".join("?" for _ in candidate_ids)
        with self._connect() as db:
            rows = db.execute(
                f"""
                select raw_json
                from entities
                where id in ({placeholders})
                   or entity_type != 'Task6'
                   or task_type in (1, 2)
                """,
                candidate_ids,
            ).fetchall()
        return {item["id"]: item for item in (json.loads(row["raw_json"]) for row in rows)}

    def apply_history_items(
        self,
        items: list[dict[str, Any]],
        *,
        latest_item_index: int,
        latest_schema_version: int | None = None,
        latest_server_index: int | None = None,
        mark_synced: bool = True,
    ) -> None:
        touched_ids = [entity_id for wrapper in items for entity_id in wrapper]
        state = self.load_state()
        fold_history_items(state, items)

        with self._connect() as db:
            for entity_id in dict.fromkeys(touched_ids):
                item = state.get(entity_id)
                if item is not None:
                    self._upsert_entity(db, item)
            self._set_meta(db, "latest_item_index", latest_item_index)
            if mark_synced:
                self._set_meta(db, "last_synced_at", time.time())
            if latest_schema_version is not None:
                self._set_meta(db, "latest_schema_version", latest_schema_version)
            if latest_server_index is not None:
                self._set_meta(db, "latest_server_index", latest_server_index)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> bool:
        columns = {row["name"] for row in db.execute(f"pragma table_info({table})").fetchall()}
        if column not in columns:
            db.execute(f"alter table {table} add column {column} {definition}")
            return True
        return False

    @staticmethod
    def _backfill_derived_columns(db: sqlite3.Connection) -> None:
        rows = db.execute(
            """
            select id, raw_json
            from entities
            where created_at is null or start_at is null or deadline_at is null
            """
        ).fetchall()
        for row in rows:
            item = json.loads(row["raw_json"])
            db.execute(
                """
                update entities
                set created_at = ?, start_at = ?, deadline_at = ?
                where id = ?
                """,
                (item.get("cd"), _start_at(item), item.get("dd"), row["id"]),
            )

    @staticmethod
    def _set_meta(db: sqlite3.Connection, key: str, value: str | int | float) -> None:
        db.execute(
            """
            insert into sync_meta (key, value)
            values (?, ?)
            on conflict(key) do update set value = excluded.value
            """,
            (key, str(value)),
        )

    @staticmethod
    def _upsert_entity(db: sqlite3.Connection, item: dict[str, Any]) -> None:
        db.execute(
            """
            insert into entities (
                id, entity_type, deleted, title, task_type, status, trashed, created_at, start_at, deadline_at, modified_at, raw_json
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(id) do update set
                entity_type = excluded.entity_type,
                deleted = excluded.deleted,
                title = excluded.title,
                task_type = excluded.task_type,
                status = excluded.status,
                trashed = excluded.trashed,
                created_at = excluded.created_at,
                start_at = excluded.start_at,
                deadline_at = excluded.deadline_at,
                modified_at = excluded.modified_at,
                raw_json = excluded.raw_json
            """,
            (
                item["id"],
                item.get("e"),
                1 if item.get("deleted") else 0,
                item.get("tt"),
                item.get("tp"),
                item.get("ss"),
                1 if item.get("tr") else 0,
                item.get("cd"),
                _start_at(item),
                item.get("dd"),
                item.get("md"),
                json.dumps(item, separators=(",", ":"), ensure_ascii=False),
            ),
        )


def _start_at(item: dict[str, Any]) -> int | float | None:
    return item.get("sr") or item.get("tir")


def _status_clauses(status: str) -> list[str]:
    if status == "all":
        return ["deleted = 0"]
    if status == "archived":
        return ["deleted = 0", "trashed = 0", "status in (2, 3)"]
    if status == "completed":
        return ["deleted = 0", "trashed = 0", "status = 3"]
    if status == "trashed":
        return ["deleted = 0", "trashed = 1"]
    if status == "deleted":
        return ["deleted = 1"]
    return ["deleted = 0", "trashed = 0", "(status is null or status not in (2, 3))"]
