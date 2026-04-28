from __future__ import annotations

import sqlite3

from things_mcp.history import todos
from things_mcp.store import EntityStore


def test_store_initializes_schema(tmp_path) -> None:
    store = EntityStore(tmp_path / "entities.sqlite")

    assert store.path.exists()
    assert store.latest_item_index() is None
    assert store.has_entities() is False


def test_store_folds_history_items_and_updates_meta(tmp_path) -> None:
    store = EntityStore(tmp_path / "entities.sqlite")

    store.apply_history_items(
        [
            {"task-1": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Old", "ss": 0}}},
            {"task-1": {"t": 1, "e": "Task6", "p": {"tt": "New", "md": 1.5}}},
            {"area-1": {"t": 0, "e": "Area3", "p": {"tt": "Area"}}},
            {"area-1": {"t": 2, "e": "Area3", "p": {}}},
        ],
        latest_item_index=4,
        latest_schema_version=301,
        latest_server_index=10,
    )

    state = store.load_state()

    assert state["task-1"]["tt"] == "New"
    assert state["task-1"]["deleted"] is False
    assert state["area-1"]["deleted"] is True
    assert store.latest_item_index() == 4
    assert store.get_meta("latest_schema_version") == "301"
    assert store.get_meta("latest_server_index") == "10"
    assert store.get_meta("last_synced_at") is not None


def test_store_lists_todos_by_start_and_deadline(tmp_path) -> None:
    store = EntityStore(tmp_path / "entities.sqlite")
    store.apply_history_items(
        [
            {
                "match": {
                    "t": 0,
                    "e": "Task6",
                    "p": {"tp": 0, "tt": "Match", "ss": 0, "tr": False, "cd": 5, "sr": 20, "dd": 30},
                }
            },
            {
                "wrong-start": {
                    "t": 0,
                    "e": "Task6",
                    "p": {"tp": 0, "tt": "Wrong start", "ss": 0, "tr": False, "cd": 5, "sr": 10, "dd": 30},
                }
            },
            {
                "wrong-deadline": {
                    "t": 0,
                    "e": "Task6",
                    "p": {"tp": 0, "tt": "Wrong deadline", "ss": 0, "tr": False, "cd": 10, "tir": 20, "dd": 40},
                }
            },
        ],
        latest_item_index=3,
    )

    result = store.list_todos(start_from=15, start_to=25, deadline_to=35)

    assert [item["id"] for item in result] == ["match"]

    created_result = store.list_todos(created_from=5, created_to=5)

    assert {item["id"] for item in created_result} == {"match", "wrong-start"}


def test_store_open_todos_excludes_logbook_items(tmp_path) -> None:
    store = EntityStore(tmp_path / "entities.sqlite")
    store.apply_history_items(
        [
            {"open": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Open", "ss": 0, "tr": False}}},
            {"done": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Done", "ss": 3, "tr": False}}},
            {"canceled": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Canceled", "ss": 2, "tr": False}}},
        ],
        latest_item_index=3,
    )

    result = store.list_todos()

    assert [item["id"] for item in result] == ["open"]

    archived = store.list_todos(status="archived")

    assert {item["id"] for item in archived} == {"canceled", "done"}


def test_store_sql_candidates_match_history_filtering(tmp_path) -> None:
    store = EntityStore(tmp_path / "entities.sqlite")
    items = [
        {"project-open": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Open", "ss": 0, "tr": False}}},
        {"project-trash": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Trash", "ss": 0, "tr": True}}},
        {
            "match": {
                "t": 0,
                "e": "Task6",
                "p": {"tp": 0, "tt": "Match", "ss": 0, "tr": False, "pr": ["project-open"], "tg": ["tag"], "sr": 20},
            }
        },
        {
            "hidden": {
                "t": 0,
                "e": "Task6",
                "p": {"tp": 0, "tt": "Hidden", "ss": 0, "tr": False, "pr": ["project-trash"], "tg": ["tag"], "sr": 20},
            }
        },
        {
            "wrong-tag": {
                "t": 0,
                "e": "Task6",
                "p": {"tp": 0, "tt": "Wrong", "ss": 0, "tr": False, "pr": ["project-open"], "tg": ["other"], "sr": 20},
            }
        },
    ]
    store.apply_history_items(items, latest_item_index=len(items))

    expected = todos(store.load_state(), tag_ids=["tag"], start_from=10, start_to=30)
    result = store.list_todos(tag_ids=["tag"], start_from=10, start_to=30)

    assert [item["id"] for item in result] == [item["id"] for item in expected] == ["match"]


def test_store_migrates_and_backfills_date_columns(tmp_path) -> None:
    path = tmp_path / "entities.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            """
            create table entities (
                id text primary key,
                entity_type text,
                deleted integer not null default 0,
                title text,
                task_type integer,
                status integer,
                trashed integer not null default 0,
                modified_at real,
                raw_json text not null
            )
            """
        )
        db.execute(
            """
            insert into entities (
                id, entity_type, deleted, title, task_type, status, trashed, modified_at, raw_json
            )
            values (
                'task', 'Task6', 0, 'Task', 0, 0, 0, 1,
                '{"id":"task","e":"Task6","tp":0,"tt":"Task","ss":0,"tr":false,"cd":10,"sr":20,"dd":30}'
            )
            """
        )

    store = EntityStore(path)

    assert [item["id"] for item in store.list_todos(created_from=10, start_from=20, deadline_to=30)] == ["task"]
