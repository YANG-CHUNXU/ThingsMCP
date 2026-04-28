from __future__ import annotations

import secrets
import time
import zlib
from collections import OrderedDict
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
TASK_LIST_CHOICES = ("inbox", "today", "anytime", "someday", "logbook")

STATUS_OPEN = 0
STATUS_CANCEL = 2
STATUS_COMPLETE = 3
STOPPED_STATUS_VALUES = {STATUS_CANCEL, STATUS_COMPLETE}
UNSET = object()

_PRESERVE = object()
_TODAY = object()
_NOW = object()

OBSERVED_TASK_LIST_PLACEMENT = {
    "inbox": {"st": 0, "sr": None, "tir": None},
    "today": {"st": 1, "sr": _TODAY, "tir": _TODAY},
    "anytime": {"st": 1, "sr": None, "tir": None},
    "someday": {"st": 2, "sr": None, "tir": None},
    "logbook": {"st": _PRESERVE, "ss": STATUS_COMPLETE, "sp": _NOW},
}


def new_entity_id(length: int = 22) -> str:
    value = int.from_bytes(secrets.token_bytes(16), "big")
    chars = []
    while value:
        value, remainder = divmod(value, 58)
        chars.append(BASE58[remainder])
    encoded = "".join(reversed(chars or ["1"]))
    return encoded.rjust(length, "1")


def parse_local_date(value: str | None, timezone_name: str) -> int | None:
    parsed = _resolve_date(value, timezone_name)
    if parsed is None:
        return None

    tz = ZoneInfo(timezone_name)
    local_midnight = datetime.combine(parsed, datetime_time.min, tzinfo=tz)
    return int(local_midnight.timestamp())


def parse_things_date(value: str | None, timezone_name: str) -> int | None:
    parsed = _resolve_date(value, timezone_name)
    if parsed is None:
        return None

    utc_midnight = datetime.combine(parsed, datetime_time.min, tzinfo=timezone.utc)
    return int(utc_midnight.timestamp())


def parse_reminder_time(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid reminder_time: {value}. Use HH:MM in 5-minute increments.")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"Invalid reminder_time: {value}. Use HH:MM in 5-minute increments.") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid reminder_time: {value}. Use HH:MM in 24-hour time.")
    if minute % 5 != 0:
        raise ValueError(f"Invalid reminder_time: {value}. Things reminders use 5-minute increments.")
    return hour * 3600 + minute * 60


def validate_title(value: str, *, field_name: str = "title") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty.")
    return text


def validate_optional_title(value: str | None, *, field_name: str = "title") -> str | None:
    if value is None:
        return None
    return validate_title(value, field_name=field_name)


def _resolve_date(value: str | None, timezone_name: str) -> date | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    tz = ZoneInfo(timezone_name)
    today = datetime.now(tz).date()
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid date: {value}. Use YYYY-MM-DD, today, or tomorrow.") from exc


def text_note(value: str) -> dict[str, Any]:
    return {
        "t": 1,
        "ch": zlib.crc32(value.encode("utf-8")) & 0xFFFFFFFF,
        "v": value,
        "_t": "tx",
    }


def resolve_task_list(list_name: str | None) -> str | None:
    if list_name is None:
        return None
    normalized = list_name.strip().lower()
    if normalized not in TASK_LIST_CHOICES:
        raise ValueError(
            f"Unknown built-in task list target: {list_name}. "
            f"Choose from {', '.join(TASK_LIST_CHOICES)}."
        )
    return normalized


def build_task_container_props(project_id: str | None = None, area_id: str | None = None) -> dict[str, Any]:
    if project_id is not None and area_id is not None:
        raise ValueError("A task can belong to at most one direct container.")
    if project_id is not None:
        return {"pr": [project_id], "ar": [], "agr": []}
    if area_id is not None:
        return {"pr": [], "ar": [area_id], "agr": []}
    return {"pr": [], "ar": [], "agr": []}


def build_task_list_props(
    list_name: str,
    *,
    current_state: dict[str, Any] | None = None,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    normalized = resolve_task_list(list_name)
    if normalized is None:
        return {}
    props = {"pr": [], "ar": [], "agr": []}
    template = OBSERVED_TASK_LIST_PLACEMENT[normalized]
    current_state = current_state or {}
    for key, value in template.items():
        props[key] = _resolve_observed_value(key, value, current_state, timezone_name=timezone_name)
    return props


def build_task_placement_props(
    *,
    project_id: str | None = None,
    area_id: str | None = None,
    list_name: str | None = None,
    current_state: dict[str, Any] | None = None,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    normalized_list = resolve_task_list(list_name)
    target_count = sum(value is not None for value in [project_id, area_id, normalized_list])
    if target_count > 1:
        raise ValueError("A task can belong to exactly one direct placement target.")

    if project_id is not None:
        return build_task_container_props(project_id=project_id)
    if area_id is not None:
        return build_task_container_props(area_id=area_id)
    if normalized_list is None:
        return {}

    props = build_task_list_props(
        normalized_list,
        current_state=current_state,
        timezone_name=timezone_name,
    )
    if normalized_list != "logbook" and (current_state or {}).get("ss") in STOPPED_STATUS_VALUES:
        props["ss"] = STATUS_OPEN
        props["sp"] = None
    return props


def build_checklist_item(parent_task_id: str, title: str, index: int, created_at: float) -> tuple[str, dict[str, Any]]:
    title = validate_title(title, field_name="checklist item title")
    entity_id = new_entity_id()
    return entity_id, {
        "t": 0,
        "e": "ChecklistItem3",
        "p": {
            "ix": -index if index else 0,
            "cd": created_at,
            "ts": [parent_task_id],
            "sp": None,
            "ss": STATUS_OPEN,
            "xx": {"sn": {}, "_t": "oo"},
            "tt": title,
            "md": created_at,
            "lt": False,
        },
    }


def build_task_create(
    title: str,
    *,
    timezone: str,
    notes: str = "",
    when: str | None = None,
    reminder_time: str | None = None,
    deadline: str | None = None,
    tag_ids: list[str] | None = None,
    checklist_items: list[str] | None = None,
    project_id: str | None = None,
    area_id: str | None = None,
    list_name: str | None = None,
) -> tuple[str, dict[str, Any]]:
    title = validate_title(title)
    if when is not None and list_name is not None:
        raise ValueError("Use either when or list_name, not both.")
    normalized_list = resolve_task_list(list_name)

    now = time.time()
    entity_id = new_entity_id()
    schedule_epoch = parse_things_date(when, timezone)
    reminder_offset = parse_reminder_time(reminder_time)
    if reminder_offset is not None and schedule_epoch is None and normalized_list != "today":
        raise ValueError("reminder_time requires when or list_name='today'.")
    deadline_epoch = parse_things_date(deadline, timezone)
    placement_state = {
        "st": 2 if schedule_epoch is not None else 0,
        "sr": schedule_epoch,
        "tir": schedule_epoch,
        "ss": STATUS_OPEN,
        "sp": None,
    }
    placement_props = build_task_placement_props(
        project_id=project_id,
        area_id=area_id,
        list_name=list_name,
        current_state=placement_state,
        timezone_name=timezone,
    )

    change_map = {
        entity_id: {
            "t": 0,
            "e": "Task6",
            "p": {
                "tp": 0,
                "sr": schedule_epoch,
                "dds": None,
                "rt": [],
                "rmd": None,
                "ss": STATUS_OPEN,
                "tr": False,
                "dl": [],
                "icp": False,
                "st": 2 if schedule_epoch is not None else 0,
                "ar": [],
                "tt": title,
                "do": 0,
                "lai": None,
                "tir": schedule_epoch,
                "tg": _dedupe(tag_ids),
                "agr": [],
                "ix": 0,
                "cd": now,
                "lt": False,
                "icc": 0,
                "ti": 0,
                "md": now,
                "dd": deadline_epoch,
                "ato": reminder_offset,
                "nt": text_note(notes),
                "icsd": None,
                "pr": [],
                "rp": None,
                "acrd": None,
                "sp": None,
                "sb": 0,
                "rr": None,
                "xx": {"sn": {}, "_t": "oo"},
                **placement_props,
            },
        }
    }
    for index, item_title in enumerate(checklist_items or []):
        checklist_id, checklist_change = build_checklist_item(entity_id, item_title, index, now)
        change_map[checklist_id] = checklist_change
    return entity_id, change_map


def build_task_update(
    entity_id: str,
    *,
    timezone: str,
    title: str | None = None,
    notes: str | object = UNSET,
    when: str | None | object = UNSET,
    reminder_time: str | None | object = UNSET,
    deadline: str | None | object = UNSET,
    tag_ids: list[str] | object = UNSET,
    project_id: str | None | object = UNSET,
    area_id: str | None | object = UNSET,
    list_name: str | None | object = UNSET,
    current_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if when is not UNSET and list_name is not UNSET:
        raise ValueError("Use either when or list_name, not both.")

    props: dict[str, Any] = {"md": time.time()}
    if title is not None:
        props["tt"] = validate_optional_title(title)
    if notes is not UNSET:
        props["nt"] = text_note("" if notes is None else str(notes))
    if tag_ids is not UNSET:
        props["tg"] = _dedupe(tag_ids if isinstance(tag_ids, list) else [])
    if when is not UNSET:
        schedule_epoch = parse_things_date(when if isinstance(when, str) or when is None else str(when), timezone)
        props["sr"] = schedule_epoch
        props["tir"] = schedule_epoch
        props["st"] = 2 if schedule_epoch is not None else 0
        if schedule_epoch is None and reminder_time is UNSET:
            props["ato"] = None
    if deadline is not UNSET:
        deadline_epoch = parse_things_date(deadline if isinstance(deadline, str) or deadline is None else str(deadline), timezone)
        props["dd"] = deadline_epoch
    if list_name is not UNSET:
        props.update(
            build_task_placement_props(
                list_name=list_name if isinstance(list_name, str) else None,
                current_state=current_state,
                timezone_name=timezone,
            )
        )
        if props.get("sr") is None and reminder_time is UNSET:
            props["ato"] = None
    elif project_id is not UNSET or area_id is not UNSET:
        props.update(
            build_task_placement_props(
                project_id=None if project_id is UNSET else project_id,
                area_id=None if area_id is UNSET else area_id,
                current_state=current_state,
            )
        )
    if reminder_time is not UNSET:
        reminder_offset = parse_reminder_time(
            reminder_time if isinstance(reminder_time, str) or reminder_time is None else str(reminder_time)
        )
        if reminder_offset is not None and not _has_scheduled_date(props, current_state):
            raise ValueError("reminder_time requires the to-do to have a Things When date.")
        props["ato"] = reminder_offset

    if list(props.keys()) == ["md"]:
        raise ValueError("No changes requested.")
    return {entity_id: {"t": 1, "e": "Task6", "p": props}}


def _has_scheduled_date(props: dict[str, Any], current_state: dict[str, Any] | None) -> bool:
    if "sr" in props:
        return props["sr"] is not None
    current_state = current_state or {}
    return current_state.get("sr") is not None or current_state.get("tir") is not None


def build_task_status_change(entity_id: str, status_value: int) -> dict[str, Any]:
    now = time.time()
    return {
        entity_id: {
            "t": 1,
            "e": "Task6",
            "p": {
                "md": now,
                "ss": status_value,
                "sp": now,
            },
        }
    }


def build_task_complete(entity_id: str) -> dict[str, Any]:
    return build_task_status_change(entity_id, STATUS_COMPLETE)


def build_task_cancel(entity_id: str) -> dict[str, Any]:
    return build_task_status_change(entity_id, STATUS_CANCEL)


def build_task_delete(entity_id: str) -> dict[str, Any]:
    return {
        entity_id: {
            "t": 1,
            "e": "Task6",
            "p": {
                "tr": True,
                "md": time.time(),
            },
        }
    }


def build_project_create(
    title: str,
    *,
    timezone: str,
    notes: str = "",
    area_ids: list[str] | None = None,
    tag_ids: list[str] | None = None,
    when: str | None = None,
    deadline: str | None = None,
) -> tuple[str, dict[str, Any]]:
    title = validate_title(title)
    now = time.time()
    entity_id = new_entity_id()
    schedule_epoch = parse_things_date(when, timezone)
    deadline_epoch = parse_things_date(deadline, timezone)
    return entity_id, {
        entity_id: {
            "t": 0,
            "e": "Task6",
            "p": {
                "tp": 1,
                "sr": schedule_epoch,
                "dds": None,
                "rt": [],
                "rmd": None,
                "ss": STATUS_OPEN,
                "tr": False,
                "dl": [],
                "icp": False,
                "st": 2 if schedule_epoch is not None else 1,
                "ar": _dedupe(area_ids),
                "tt": title,
                "do": 0,
                "lai": None,
                "tir": schedule_epoch,
                "tg": _dedupe(tag_ids),
                "agr": [],
                "ix": 0,
                "cd": now,
                "lt": False,
                "icc": 0,
                "md": now,
                "ti": 0,
                "dd": deadline_epoch,
                "ato": None,
                "nt": text_note(notes),
                "icsd": None,
                "pr": [],
                "rp": None,
                "acrd": None,
                "sp": None,
                "sb": 0,
                "rr": None,
                "xx": {"sn": {}, "_t": "oo"},
            },
        }
    }


def build_project_update(
    entity_id: str,
    *,
    timezone: str,
    title: str | None = None,
    notes: str | object = UNSET,
    area_ids: list[str] | object = UNSET,
    tag_ids: list[str] | object = UNSET,
    when: str | None | object = UNSET,
    deadline: str | None | object = UNSET,
) -> dict[str, Any]:
    props: dict[str, Any] = {"md": time.time()}
    if title is not None:
        props["tt"] = validate_optional_title(title)
    if notes is not UNSET:
        props["nt"] = text_note("" if notes is None else str(notes))
    if area_ids is not UNSET:
        props["ar"] = _dedupe(area_ids if isinstance(area_ids, list) else [])
    if tag_ids is not UNSET:
        props["tg"] = _dedupe(tag_ids if isinstance(tag_ids, list) else [])
    if when is not UNSET:
        schedule_epoch = parse_things_date(when if isinstance(when, str) or when is None else str(when), timezone)
        props["sr"] = schedule_epoch
        props["tir"] = schedule_epoch
        props["st"] = 2 if schedule_epoch is not None else 1
    if deadline is not UNSET:
        deadline_epoch = parse_things_date(deadline if isinstance(deadline, str) or deadline is None else str(deadline), timezone)
        props["dd"] = deadline_epoch
    if list(props.keys()) == ["md"]:
        raise ValueError("No changes requested.")
    return {entity_id: {"t": 1, "e": "Task6", "p": props}}


def build_project_status_change(entity_id: str, status_value: int, child_task_ids: list[str]) -> dict[str, Any]:
    now = time.time()
    change_map: OrderedDict[str, dict[str, Any]] = OrderedDict()
    change_map[entity_id] = {
        "t": 1,
        "e": "Task6",
        "p": {
            "md": now,
            "ss": status_value,
            "sp": now,
        },
    }
    for child_id in child_task_ids:
        change_map[child_id] = {
            "t": 1,
            "e": "Task6",
            "p": {
                "md": now,
                "ss": status_value,
                "sp": now,
            },
        }
    return dict(change_map)


def build_project_delete(entity_id: str) -> dict[str, Any]:
    return {
        entity_id: {
            "t": 1,
            "e": "Task6",
            "p": {
                "tr": True,
                "md": time.time(),
                "ar": [],
            },
        }
    }


def build_heading_create(title: str, project_id: str) -> tuple[str, dict[str, Any]]:
    title = validate_title(title)
    now = time.time()
    entity_id = new_entity_id()
    return entity_id, {
        entity_id: {
            "t": 0,
            "e": "Task6",
            "p": {
                "tp": 2,
                "sr": None,
                "dds": None,
                "rt": [],
                "rmd": None,
                "ss": STATUS_OPEN,
                "tr": False,
                "dl": [],
                "icp": False,
                "st": 1,
                "ar": [],
                "tt": title,
                "do": 0,
                "lai": None,
                "tir": None,
                "tg": [],
                "agr": [],
                "ix": 0,
                "cd": now,
                "lt": False,
                "icc": 0,
                "md": now,
                "ti": 0,
                "dd": None,
                "ato": None,
                "nt": text_note(""),
                "icsd": None,
                "pr": [project_id],
                "rp": None,
                "acrd": None,
                "sp": None,
                "sb": 0,
                "rr": None,
                "xx": {"sn": {}, "_t": "oo"},
            },
        }
    }


def build_heading_update(
    entity_id: str,
    *,
    title: str | None = None,
    notes: str | object = UNSET,
    project_id: str | object = UNSET,
    tag_ids: list[str] | object = UNSET,
) -> dict[str, Any]:
    props: dict[str, Any] = {"md": time.time()}
    if title is not None:
        props["tt"] = validate_optional_title(title)
    if notes is not UNSET:
        props["nt"] = text_note("" if notes is None else str(notes))
    if project_id is not UNSET:
        props["pr"] = [project_id] if project_id is not None else []
    if tag_ids is not UNSET:
        props["tg"] = _dedupe(tag_ids if isinstance(tag_ids, list) else [])
    if list(props.keys()) == ["md"]:
        raise ValueError("No changes requested.")
    return {entity_id: {"t": 1, "e": "Task6", "p": props}}


def build_area_create(title: str, *, tag_ids: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    title = validate_title(title)
    entity_id = new_entity_id()
    return entity_id, {
        entity_id: {
            "t": 0,
            "e": "Area3",
            "p": {
                "xx": {"sn": {}, "_t": "oo"},
                "ix": 0,
                "tg": _dedupe(tag_ids),
                "tt": title,
            },
        }
    }


def build_area_update(
    entity_id: str,
    *,
    title: str | None = None,
    tag_ids: list[str] | object = UNSET,
) -> dict[str, Any]:
    props: dict[str, Any] = {}
    if title is not None:
        props["tt"] = validate_optional_title(title)
    if tag_ids is not UNSET:
        props["tg"] = _dedupe(tag_ids if isinstance(tag_ids, list) else [])
    if not props:
        raise ValueError("No changes requested.")
    return {entity_id: {"t": 1, "e": "Area3", "p": props}}


def build_area_delete(entity_id: str) -> dict[str, Any]:
    return {
        entity_id: {
            "t": 2,
            "e": "Area3",
            "p": {},
        }
    }


def build_tag_create(title: str, *, parent_id: str | None = None) -> tuple[str, dict[str, Any]]:
    title = validate_title(title)
    entity_id = new_entity_id()
    return entity_id, {
        entity_id: {
            "t": 0,
            "e": "Tag4",
            "p": {
                "xx": {"sn": {}, "_t": "oo"},
                "pn": [parent_id] if parent_id else [],
                "ix": 0,
                "sh": None,
                "tt": title,
            },
        }
    }


def build_tag_update(
    entity_id: str,
    *,
    title: str | None = None,
    parent_id: str | None | object = UNSET,
    clear_parent: bool = False,
) -> dict[str, Any]:
    if clear_parent and parent_id is not UNSET:
        raise ValueError("Use either parent_id or clear_parent, not both.")

    props: dict[str, Any] = {}
    if title is not None:
        props["tt"] = validate_optional_title(title)
    if clear_parent:
        props["pn"] = []
    elif parent_id is not UNSET:
        props["pn"] = [parent_id] if parent_id is not None else []
    if not props:
        raise ValueError("No changes requested.")
    return {entity_id: {"t": 1, "e": "Tag4", "p": props}}


def build_tag_delete(entity_id: str) -> dict[str, Any]:
    return {
        entity_id: {
            "t": 2,
            "e": "Tag4",
            "p": {},
        }
    }


def validate_task_state(state: dict[str, dict[str, Any]], entity_id: str) -> dict[str, Any]:
    item = _require_item(state, entity_id, entity_name="Task")
    if item.get("tr"):
        raise ValueError(f"Task not found in current cloud state: {entity_id}")
    if item.get("tp") != 0:
        raise ValueError(f"Entity is not a regular task (tp=0): {entity_id}")
    return item


def validate_project_state(state: dict[str, dict[str, Any]], entity_id: str) -> dict[str, Any]:
    item = _require_item(state, entity_id, entity_name="Project")
    if item.get("tr"):
        raise ValueError(f"Project not found in current cloud state: {entity_id}")
    if item.get("tp") != 1:
        raise ValueError(f"Entity is not a project (tp=1): {entity_id}")
    return item


def validate_heading_state(state: dict[str, dict[str, Any]], entity_id: str) -> dict[str, Any]:
    item = _require_item(state, entity_id, entity_name="Heading")
    if item.get("tr"):
        raise ValueError(f"Heading not found in current cloud state: {entity_id}")
    if item.get("tp") != 2:
        raise ValueError(f"Entity is not a heading (tp=2): {entity_id}")
    return item


def validate_area_state(state: dict[str, dict[str, Any]], entity_id: str) -> dict[str, Any]:
    item = _require_item(state, entity_id, entity_name="Area")
    if item.get("tr"):
        raise ValueError(f"Area not found in current cloud state: {entity_id}")
    if item.get("e") != "Area3":
        raise ValueError(f"Entity is not an area: {entity_id}")
    return item


def validate_tag_state(state: dict[str, dict[str, Any]], entity_id: str) -> dict[str, Any]:
    item = _require_item(state, entity_id, entity_name="Tag")
    if item.get("tr"):
        raise ValueError(f"Tag not found in current cloud state: {entity_id}")
    if item.get("e") != "Tag4":
        raise ValueError(f"Entity is not a tag: {entity_id}")
    return item


def collect_active_project_heading_ids(state: dict[str, dict[str, Any]], project_id: str) -> list[str]:
    return sorted(
        entity_id
        for entity_id, item in state.items()
        if _is_active(item) and item.get("tp") == 2 and project_id in (item.get("pr") or [])
    )


def validate_area_ids(state: dict[str, dict[str, Any]], area_ids: list[str] | None) -> list[str]:
    ids = _dedupe(area_ids)
    for entity_id in ids:
        validate_area_state(state, entity_id)
    return ids


def validate_tag_ids(state: dict[str, dict[str, Any]], tag_ids: list[str] | None) -> list[str]:
    ids = _dedupe(tag_ids)
    for entity_id in ids:
        validate_tag_state(state, entity_id)
    return ids


def collect_unfinished_project_task_ids(state: dict[str, dict[str, Any]], project_id: str) -> list[str]:
    heading_ids = {
        entity_id
        for entity_id, item in state.items()
        if _is_active(item) and item.get("tp") == 2 and project_id in (item.get("pr") or [])
    }
    child_ids = set()
    for entity_id, item in state.items():
        if not _is_active(item):
            continue
        if item.get("tp") != 0:
            continue
        if item.get("ss") in STOPPED_STATUS_VALUES:
            continue
        if project_id in (item.get("pr") or []):
            child_ids.add(entity_id)
            continue
        if heading_ids and heading_ids.intersection(item.get("agr") or []):
            child_ids.add(entity_id)
    return sorted(child_ids)


def _dedupe(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(values or []))


def _resolve_observed_value(
    key: str,
    value: Any,
    current_state: dict[str, Any],
    *,
    timezone_name: str | None = None,
) -> Any:
    if value is _TODAY:
        return parse_things_date("today", timezone_name or "UTC")
    if value is _NOW:
        return time.time()
    if value is _PRESERVE:
        if key == "st":
            return current_state.get("st", 0)
        return current_state.get(key)
    return value


def _require_item(state: dict[str, dict[str, Any]], entity_id: str, *, entity_name: str) -> dict[str, Any]:
    item = dict(state.get(entity_id) or {})
    if not item or item.get("deleted"):
        raise ValueError(f"{entity_name} not found in current cloud state: {entity_id}")
    return item


def _is_active(item: dict[str, Any]) -> bool:
    return bool(item) and not item.get("deleted") and not item.get("tr")
