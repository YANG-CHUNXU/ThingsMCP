from __future__ import annotations

from typing import Any

from .cloud_client import ThingsCloudClient


HISTORY_ITEMS_BATCH_SIZE = 2500


def load_current_state(client: ThingsCloudClient) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    start_index = 0
    while True:
        body = client.history_items(start_index)
        items = body.get("items") or []
        fold_history_items(state, items)
        if not items:
            return state
        start_index += len(items)
        current_index = body.get("current-item-index", 0)
        if len(items) < HISTORY_ITEMS_BATCH_SIZE or start_index >= current_index:
            return state


def fold_history_items(
    state: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    for wrapper in items:
        for entity_id, item in wrapper.items():
            entity_type = item.get("e")
            op = item.get("t")
            props = item.get("p") or {}

            if op == 0:
                state[entity_id] = {
                    "id": entity_id,
                    "e": entity_type,
                    "deleted": False,
                    **props,
                }
            elif op == 1:
                current = dict(state.get(entity_id) or {"id": entity_id, "e": entity_type})
                current["e"] = entity_type or current.get("e")
                current["deleted"] = False
                current.update(props)
                state[entity_id] = current
            elif op == 2:
                current = dict(state.get(entity_id) or {"id": entity_id, "e": entity_type})
                current["e"] = entity_type or current.get("e")
                current["deleted"] = True
                state[entity_id] = current
    return state


def todos(
    state: dict[str, dict[str, Any]],
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
    tag_ids = tag_ids or []
    rows = []
    for item in state.values():
        if item.get("e") != "Task6" or item.get("tp") != 0:
            continue
        if not _status_matches(item, status):
            continue
        if status not in {"trashed", "deleted"} and not _task_parent_matches(state, item):
            continue
        if project_id and project_id not in item.get("pr", []):
            continue
        if area_id and area_id not in item.get("ar", []):
            continue
        if tag_ids and not set(tag_ids).issubset(set(item.get("tg", []))):
            continue
        if not _date_range_matches(item.get("cd"), created_from, created_to):
            continue
        if not _date_range_matches(_start_at(item), start_from, start_to):
            continue
        if not _date_range_matches(item.get("dd"), deadline_from, deadline_to):
            continue
        rows.append(public_item(item))
    return sorted(rows, key=lambda row: row.get("md") or row.get("cd") or 0, reverse=True)[: max(limit, 0)]


def projects(
    state: dict[str, dict[str, Any]],
    *,
    status: str = "open",
    created_from: int | None = None,
    created_to: int | None = None,
    deadline_from: int | None = None,
    deadline_to: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return _task_type(
        state,
        task_type=1,
        status=status,
        created_from=created_from,
        created_to=created_to,
        deadline_from=deadline_from,
        deadline_to=deadline_to,
        limit=limit,
    )


def inbox_todos(
    state: dict[str, dict[str, Any]],
    *,
    tag_ids: list[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    tag_ids = tag_ids or []
    rows = []
    for item in state.values():
        if item.get("e") != "Task6" or item.get("tp") != 0:
            continue
        if not _status_matches(item, "open") or not _task_parent_matches(state, item):
            continue
        if item.get("pr") or item.get("ar") or item.get("agr"):
            continue
        if item.get("st", 0) != 0:
            continue
        if tag_ids and not set(tag_ids).issubset(set(item.get("tg", []))):
            continue
        rows.append(public_item(item))
    return sorted(rows, key=lambda row: row.get("md") or row.get("cd") or 0, reverse=True)[: max(limit, 0)]


def deadline_todos(
    state: dict[str, dict[str, Any]],
    *,
    tag_ids: list[str] | None = None,
    deadline_from: int | None = None,
    deadline_to: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = [
        item
        for item in todos(
            state,
            status="open",
            tag_ids=tag_ids,
            deadline_from=deadline_from,
            deadline_to=deadline_to,
            limit=10_000,
        )
        if item.get("dd") is not None
    ]
    return rows[: max(limit, 0)]


def headings(
    state: dict[str, dict[str, Any]],
    *,
    project_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = [
        public_item(item)
        for item in state.values()
        if item.get("e") == "Task6"
        and item.get("tp") == 2
        and _status_matches(item, "open")
        and _heading_parent_matches(state, item, project_id=project_id)
    ]
    return sorted(rows, key=lambda row: row.get("tt") or "")[: max(limit, 0)]


def areas(
    state: dict[str, dict[str, Any]],
    *,
    status: str = "open",
    created_from: int | None = None,
    created_to: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = [
        public_item(item)
        for item in state.values()
        if item.get("e") == "Area3" and _status_matches(item, status)
        and _date_range_matches(item.get("cd"), created_from, created_to)
    ]
    return sorted(rows, key=lambda row: row.get("tt") or "")[: max(limit, 0)]


def tags(
    state: dict[str, dict[str, Any]],
    *,
    status: str = "open",
    created_from: int | None = None,
    created_to: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = [
        public_item(item)
        for item in state.values()
        if item.get("e") == "Tag4" and _status_matches(item, status)
        and _date_range_matches(item.get("cd"), created_from, created_to)
    ]
    return sorted(rows, key=lambda row: row.get("tt") or "")[: max(limit, 0)]


def get_item(state: dict[str, dict[str, Any]], entity_id: str) -> dict[str, Any] | None:
    item = state.get(entity_id)
    return public_item(item) if item else None


def search_todos(
    state: dict[str, dict[str, Any]],
    query: str,
    *,
    status: str = "all",
    created_from: int | None = None,
    created_to: int | None = None,
    deadline_from: int | None = None,
    deadline_to: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    needle = query.casefold().strip()
    if not needle:
        return []
    matches = []
    for item in todos(
        state,
        status=status,
        created_from=created_from,
        created_to=created_to,
        deadline_from=deadline_from,
        deadline_to=deadline_to,
        limit=10_000,
    ):
        notes = item.get("nt", {})
        note_text = notes.get("v", "") if isinstance(notes, dict) else ""
        haystack = f"{item.get('tt', '')}\n{note_text}".casefold()
        if needle in haystack:
            matches.append(item)
    return matches[: max(limit, 0)]


def search_projects(
    state: dict[str, dict[str, Any]],
    query: str,
    *,
    status: str = "all",
    limit: int = 100,
) -> list[dict[str, Any]]:
    needle = query.casefold().strip()
    if not needle:
        return []
    matches = []
    for item in projects(state, status=status, limit=10_000):
        notes = item.get("nt", {})
        note_text = notes.get("v", "") if isinstance(notes, dict) else ""
        haystack = f"{item.get('tt', '')}\n{note_text}".casefold()
        if needle in haystack:
            matches.append(item)
    return matches[: max(limit, 0)]


def search_tags(
    state: dict[str, dict[str, Any]],
    query: str,
    *,
    status: str = "all",
    limit: int = 100,
) -> list[dict[str, Any]]:
    needle = query.casefold().strip()
    if not needle:
        return []
    matches = [item for item in tags(state, status=status, limit=10_000) if needle in str(item.get("tt", "")).casefold()]
    return matches[: max(limit, 0)]


def public_item(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    status = result.get("ss")
    result["trashed"] = bool(result.get("tr"))
    result["completed"] = status == 3
    result["canceled"] = status == 2
    result["archived"] = status in {2, 3}
    result["in_logbook"] = result["archived"]
    return result


def _task_type(
    state: dict[str, dict[str, Any]],
    *,
    task_type: int,
    status: str,
    created_from: int | None = None,
    created_to: int | None = None,
    deadline_from: int | None = None,
    deadline_to: int | None = None,
    limit: int,
) -> list[dict[str, Any]]:
    rows = [
        public_item(item)
        for item in state.values()
        if item.get("e") == "Task6"
        and item.get("tp") == task_type
        and _status_matches(item, status)
        and _task_type_is_visible(state, item, task_type=task_type, status=status)
        and _date_range_matches(item.get("cd"), created_from, created_to)
        and _date_range_matches(item.get("dd"), deadline_from, deadline_to)
    ]
    return sorted(rows, key=lambda row: row.get("tt") or "")[: max(limit, 0)]


def _status_matches(item: dict[str, Any], status: str) -> bool:
    deleted = bool(item.get("deleted"))
    trashed = bool(item.get("tr"))
    completed = item.get("ss") == 3
    archived = item.get("ss") in {2, 3}
    if status == "all":
        return not deleted
    if status == "archived":
        return not deleted and not trashed and archived
    if status == "completed":
        return not deleted and not trashed and completed
    if status == "trashed":
        return not deleted and trashed
    if status == "deleted":
        return deleted
    return not deleted and not trashed and not archived


def _start_at(item: dict[str, Any]) -> int | float | None:
    return item.get("sr") or item.get("tir")


def _date_range_matches(value: Any, start: int | None, end: int | None) -> bool:
    if start is None and end is None:
        return True
    if value is None:
        return False
    if start is not None and value < start:
        return False
    if end is not None and value > end:
        return False
    return True


def _heading_parent_matches(state: dict[str, dict[str, Any]], item: dict[str, Any], *, project_id: str | None) -> bool:
    parent_ids = item.get("pr") or []
    if project_id is not None and project_id not in parent_ids:
        return False
    return _parent_chain_matches(state, parent_ids, lambda parent: _project_is_open_parent(state, parent))


def _task_type_is_visible(
    state: dict[str, dict[str, Any]],
    item: dict[str, Any],
    *,
    task_type: int,
    status: str,
) -> bool:
    if task_type == 1:
        return status in {"trashed", "deleted"} or _project_parent_matches(state, item)
    if task_type == 2:
        return status in {"trashed", "deleted"} or _heading_parent_matches(state, item, project_id=None)
    return True


def _task_parent_matches(state: dict[str, dict[str, Any]], item: dict[str, Any]) -> bool:
    if item.get("pr") and not _parent_chain_matches(
        state,
        item.get("pr") or [],
        lambda parent: _project_is_open_parent(state, parent),
    ):
        return False
    if item.get("ar") and not _parent_chain_matches(state, item.get("ar") or [], _area_is_active):
        return False
    if item.get("agr") and not _parent_chain_matches(
        state,
        item.get("agr") or [],
        lambda parent: _heading_is_open_parent(state, parent),
    ):
        return False
    return True


def _project_parent_matches(state: dict[str, dict[str, Any]], item: dict[str, Any]) -> bool:
    return _parent_chain_matches(state, item.get("ar") or [], _area_is_active)


def _heading_is_open_parent(state: dict[str, Any], item: dict[str, Any]) -> bool:
    return bool(item) and item.get("tp") == 2 and _status_matches(item, "open") and _heading_parent_matches(state, item, project_id=None)


def _project_is_open_parent(state: dict[str, Any], item: dict[str, Any]) -> bool:
    if not bool(item) or item.get("tp") != 1 or not _status_matches(item, "open"):
        return False
    return _project_parent_matches(state, item)


def _area_is_active(item: dict[str, Any]) -> bool:
    return _is_active(item) and item.get("e") == "Area3"


def _is_active(item: dict[str, Any]) -> bool:
    return bool(item) and not item.get("deleted") and not item.get("tr")


def _parent_chain_matches(
    state: dict[str, dict[str, Any]],
    parent_ids: list[str],
    predicate,
) -> bool:
    if not parent_ids:
        return True
    known_parents = [state[parent_id] for parent_id in parent_ids if parent_id in state]
    if not known_parents:
        return True
    return any(predicate(parent) for parent in known_parents)
