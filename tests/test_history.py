from __future__ import annotations

from things_mcp.history import (
    areas,
    deadline_todos,
    fold_history_items,
    get_item,
    headings,
    inbox_todos,
    projects,
    search_projects,
    search_tags,
    search_todos,
    tags,
    todos,
)


def test_fold_history_items_create_update_delete() -> None:
    state = fold_history_items(
        {},
        [
            {"task-1": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Old", "ss": 0}}},
            {"task-1": {"t": 1, "e": "Task6", "p": {"tt": "New"}}},
            {"area-1": {"t": 0, "e": "Area3", "p": {"tt": "Area"}}},
            {"area-1": {"t": 2, "e": "Area3", "p": {}}},
        ],
    )

    assert state["task-1"]["tt"] == "New"
    assert state["task-1"]["deleted"] is False
    assert state["area-1"]["deleted"] is True


def test_todo_status_filters_and_search() -> None:
    state = fold_history_items(
        {},
        [
            {"open": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Buy milk", "ss": 0, "tr": False}}},
            {"done": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Done", "ss": 3, "tr": False}}},
            {"canceled": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Canceled", "ss": 2, "tr": False}}},
            {"trash": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Trash", "ss": 0, "tr": True}}},
            {"project": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Project", "ss": 0, "tr": False}}},
        ],
    )

    assert [item["id"] for item in todos(state)] == ["open"]
    assert {item["id"] for item in todos(state, status="archived")} == {"canceled", "done"}
    assert [item["id"] for item in todos(state, status="completed")] == ["done"]
    assert [item["id"] for item in todos(state, status="trashed")] == ["trash"]
    assert [item["id"] for item in search_todos(state, "milk")] == ["open"]
    assert [item["id"] for item in search_todos(state, "done", status="archived")] == ["done"]


def test_convenience_todo_filters_and_entity_searches() -> None:
    state = fold_history_items(
        {},
        [
            {"inbox": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Inbox", "ss": 0, "tr": False, "st": 0}}},
            {"anytime": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Anytime", "ss": 0, "tr": False, "st": 1}}},
            {"project": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Alpha Project", "nt": {"v": "Notes"}}}},
            {
                "deadline": {
                    "t": 0,
                    "e": "Task6",
                    "p": {"tp": 0, "tt": "Deadline", "ss": 0, "tr": False, "pr": ["project"], "dd": 30},
                }
            },
            {"tag": {"t": 0, "e": "Tag4", "p": {"tt": "Focus"}}},
        ],
    )

    assert [item["id"] for item in inbox_todos(state)] == ["inbox"]
    assert [item["id"] for item in deadline_todos(state, deadline_to=30)] == ["deadline"]
    assert [item["id"] for item in search_projects(state, "notes")] == ["project"]
    assert [item["id"] for item in search_tags(state, "focus")] == ["tag"]


def test_todo_start_and_deadline_filters() -> None:
    state = fold_history_items(
        {},
        [
            {
                "match": {
                    "t": 0,
                    "e": "Task6",
                    "p": {"tp": 0, "tt": "Match", "ss": 0, "tr": False, "cd": 5, "sr": 20, "dd": 30},
                }
            },
            {
                "early": {
                    "t": 0,
                    "e": "Task6",
                    "p": {"tp": 0, "tt": "Early", "ss": 0, "tr": False, "cd": 5, "sr": 10, "dd": 30},
                }
            },
            {
                "late-deadline": {
                    "t": 0,
                    "e": "Task6",
                    "p": {"tp": 0, "tt": "Late", "ss": 0, "tr": False, "cd": 5, "tir": 20, "dd": 40},
                }
            },
            {
                "unscheduled": {
                    "t": 0,
                    "e": "Task6",
                    "p": {"tp": 0, "tt": "Unscheduled", "ss": 0, "tr": False},
                }
            },
        ],
    )

    result = todos(state, start_from=15, start_to=25, deadline_to=35)

    assert [item["id"] for item in result] == ["match"]

    created_result = todos(state, created_from=5, created_to=5)

    assert {item["id"] for item in created_result} == {"match", "early", "late-deadline"}


def test_lists_and_get_item() -> None:
    state = fold_history_items(
        {},
        [
            {"area": {"t": 0, "e": "Area3", "p": {"tt": "Area"}}},
            {"trashed-area": {"t": 0, "e": "Area3", "p": {"tt": "Trashed Area", "tr": True}}},
            {"deleted-area": {"t": 0, "e": "Area3", "p": {"tt": "Deleted Area"}}},
            {"deleted-area": {"t": 2, "e": "Area3", "p": {}}},
            {"tag": {"t": 0, "e": "Tag4", "p": {"tt": "Tag"}}},
            {"trashed-tag": {"t": 0, "e": "Tag4", "p": {"tt": "Trashed Tag", "tr": True}}},
            {"deleted-tag": {"t": 0, "e": "Tag4", "p": {"tt": "Deleted Tag"}}},
            {"deleted-tag": {"t": 2, "e": "Tag4", "p": {}}},
            {"project": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Project", "tr": False}}},
            {"logged-project": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Logged", "ss": 3, "tr": False}}},
            {"canceled-project": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Canceled", "ss": 2, "tr": False}}},
            {"trashed-project": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Trashed", "ss": 0, "tr": True}}},
            {"dated-project": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Dated", "cd": 20, "dd": 30, "tr": False}}},
        ],
    )

    assert [item["id"] for item in areas(state)] == ["area"]
    assert [item["id"] for item in areas(state, status="trashed")] == ["trashed-area"]
    assert [item["id"] for item in areas(state, status="deleted")] == ["deleted-area"]
    assert [item["id"] for item in tags(state)] == ["tag"]
    assert [item["id"] for item in tags(state, status="trashed")] == ["trashed-tag"]
    assert [item["id"] for item in tags(state, status="deleted")] == ["deleted-tag"]
    assert [item["id"] for item in projects(state)] == ["dated-project", "project"]
    assert [item["id"] for item in projects(state, status="archived")] == ["canceled-project", "logged-project"]
    assert [item["id"] for item in projects(state, status="completed")] == ["logged-project"]
    assert [item["id"] for item in projects(state, status="trashed")] == ["trashed-project"]
    assert [item["id"] for item in projects(state, created_from=20, created_to=20, deadline_to=30)] == ["dated-project"]
    project_rows = {item["id"]: item for item in projects(state, status="all")}
    assert project_rows["project"]["in_logbook"] is False
    assert project_rows["logged-project"]["archived"] is True
    assert project_rows["logged-project"]["in_logbook"] is True
    assert project_rows["canceled-project"]["canceled"] is True
    assert project_rows["canceled-project"]["in_logbook"] is True
    assert get_item(state, "tag")["tt"] == "Tag"
    assert get_item(state, "missing") is None


def test_headings_can_filter_by_project() -> None:
    state = fold_history_items(
        {},
        [
            {"heading-a": {"t": 0, "e": "Task6", "p": {"tp": 2, "tt": "A", "pr": ["project-a"]}}},
            {"heading-b": {"t": 0, "e": "Task6", "p": {"tp": 2, "tt": "B", "pr": ["project-b"]}}},
            {"heading-c": {"t": 0, "e": "Task6", "p": {"tp": 2, "tt": "C", "pr": ["project-a"], "tr": True}}},
        ],
    )

    assert [item["id"] for item in headings(state, project_id="project-a")] == ["heading-a"]


def test_headings_exclude_archived_parent_projects() -> None:
    state = fold_history_items(
        {},
        [
            {"project-open": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Open", "ss": 0}}},
            {"project-done": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Done", "ss": 3}}},
            {"heading-open": {"t": 0, "e": "Task6", "p": {"tp": 2, "tt": "A", "pr": ["project-open"]}}},
            {"heading-done": {"t": 0, "e": "Task6", "p": {"tp": 2, "tt": "B", "pr": ["project-done"]}}},
        ],
    )

    assert [item["id"] for item in headings(state)] == ["heading-open"]


def test_todos_exclude_items_under_trashed_project_or_heading() -> None:
    state = fold_history_items(
        {},
        [
            {"area-open": {"t": 0, "e": "Area3", "p": {"tt": "Open Area"}}},
            {"area-trash": {"t": 0, "e": "Area3", "p": {"tt": "Trash Area", "tr": True}}},
            {"project-open": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Open", "ss": 0, "ar": ["area-open"]}}},
            {"project-trash": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Trash", "ss": 0, "tr": True}}},
            {"project-in-trash-area": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Hidden", "ss": 0, "ar": ["area-trash"]}}},
            {"heading-open": {"t": 0, "e": "Task6", "p": {"tp": 2, "tt": "Heading", "pr": ["project-open"]}}},
            {"heading-under-trashed-project": {"t": 0, "e": "Task6", "p": {"tp": 2, "tt": "Hidden Heading", "pr": ["project-trash"]}}},
            {"task-open": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Visible", "ss": 0, "pr": ["project-open"]}}},
            {"task-under-trashed-project": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Hidden Project", "ss": 0, "pr": ["project-trash"]}}},
            {"task-under-trashed-heading": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Hidden Heading", "ss": 0, "agr": ["heading-under-trashed-project"]}}},
            {"task-under-project-in-trash-area": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Hidden Area", "ss": 0, "pr": ["project-in-trash-area"]}}},
        ],
    )

    assert [item["id"] for item in todos(state)] == ["task-open"]
    assert [item["id"] for item in projects(state)] == ["project-open"]
    assert [item["id"] for item in headings(state)] == ["heading-open"]
