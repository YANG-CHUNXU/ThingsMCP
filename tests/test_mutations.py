from __future__ import annotations

import re
import time
import zlib

import pytest

from things_mcp.mutations import (
    BASE58,
    STATUS_CANCEL,
    STATUS_COMPLETE,
    UNSET,
    build_area_create,
    build_area_delete,
    build_area_update,
    collect_active_project_heading_ids,
    build_heading_create,
    build_heading_update,
    build_project_create,
    build_project_delete,
    build_project_status_change,
    build_project_update,
    build_tag_create,
    build_tag_delete,
    build_tag_update,
    build_task_cancel,
    build_task_complete,
    build_task_create,
    build_task_delete,
    build_task_placement_props,
    build_task_update,
    collect_unfinished_project_task_ids,
    new_entity_id,
    parse_local_date,
    parse_reminder_time,
    parse_things_date,
    text_note,
    validate_area_state,
    validate_tag_state,
)


def test_new_entity_id_shape() -> None:
    entity_id = new_entity_id()
    assert len(entity_id) == 22
    assert set(entity_id).issubset(set(BASE58))
    assert re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{22}", entity_id)


def test_parse_local_date_absolute() -> None:
    assert parse_local_date("2026-04-22", "Asia/Shanghai") == 1776787200


def test_parse_things_date_absolute_uses_utc_midnight() -> None:
    assert parse_things_date("2026-04-26", "Asia/Shanghai") == 1777161600


def test_parse_reminder_time_uses_seconds_after_midnight() -> None:
    assert parse_reminder_time("04:15") == 15300
    assert parse_reminder_time("15:20") == 55200


def test_parse_reminder_time_rejects_non_five_minute_increment() -> None:
    with pytest.raises(ValueError, match="5-minute"):
        parse_reminder_time("04:17")


def test_text_note_crc32() -> None:
    note = text_note("hello")
    assert note == {
        "t": 1,
        "ch": zlib.crc32(b"hello") & 0xFFFFFFFF,
        "v": "hello",
        "_t": "tx",
    }


def test_build_task_create_matches_known_shape() -> None:
    entity_id, change_map = build_task_create(
        "Title",
        timezone="Asia/Shanghai",
        notes="Notes",
        when="2026-04-22",
        reminder_time="14:05",
        deadline="2026-04-23",
        tag_ids=["tag-a", "tag-a", "tag-b"],
        checklist_items=["one", "two"],
    )

    task = change_map[entity_id]
    props = task["p"]
    assert task["t"] == 0
    assert task["e"] == "Task6"
    assert props["tp"] == 0
    assert props["tt"] == "Title"
    assert props["nt"]["v"] == "Notes"
    assert props["tg"] == ["tag-a", "tag-b"]
    assert props["sr"] == 1776816000
    assert props["tir"] == 1776816000
    assert props["ato"] == 50700
    assert props["rmd"] is None
    assert props["st"] == 2
    assert props["dd"] == 1776902400
    checklist = [value for key, value in change_map.items() if key != entity_id]
    assert len(checklist) == 2
    assert checklist[0]["e"] == "ChecklistItem3"
    assert checklist[0]["p"]["ts"] == [entity_id]


def test_task_create_today_list_uses_observed_today_mapping() -> None:
    entity_id, change_map = build_task_create(
        "Today",
        timezone="Asia/Shanghai",
        list_name="today",
        reminder_time="09:00",
    )
    props = change_map[entity_id]["p"]

    assert props["pr"] == []
    assert props["ar"] == []
    assert props["agr"] == []
    assert props["st"] == 1
    assert props["sr"] == parse_things_date("today", "Asia/Shanghai")
    assert props["sr"] == props["tir"]
    assert props["ato"] == 32400


def test_task_create_logbook_defaults_to_completed_inbox_state() -> None:
    before = time.time()
    entity_id, change_map = build_task_create("Logbook", timezone="Asia/Shanghai", list_name="logbook")
    after = time.time()
    props = change_map[entity_id]["p"]

    assert props["st"] == 0
    assert props["ss"] == STATUS_COMPLETE
    assert before <= props["sp"] <= after


def test_task_create_rejects_when_with_list_target() -> None:
    with pytest.raises(ValueError, match="either when or list_name"):
        build_task_create("Conflicting", timezone="Asia/Shanghai", when="tomorrow", list_name="anytime")


def test_task_create_rejects_reminder_without_date() -> None:
    with pytest.raises(ValueError, match="reminder_time requires"):
        build_task_create("Reminder", timezone="Asia/Shanghai", reminder_time="09:00")


def test_builders_reject_empty_titles() -> None:
    with pytest.raises(ValueError, match="title"):
        build_task_create(" ", timezone="Asia/Shanghai")
    with pytest.raises(ValueError, match="title"):
        build_task_update("TASK_ID", timezone="Asia/Shanghai", title="")


def test_task_update_requires_change() -> None:
    with pytest.raises(ValueError, match="No changes"):
        build_task_update("task-id", timezone="Asia/Shanghai")


def test_task_update_list_clears_direct_container_and_logged_status() -> None:
    change_map = build_task_update(
        "TASK_ID",
        timezone="Asia/Shanghai",
        list_name="anytime",
        current_state={"st": 1, "ss": STATUS_COMPLETE, "sp": 123.0},
    )
    props = change_map["TASK_ID"]["p"]

    assert props["pr"] == []
    assert props["ar"] == []
    assert props["agr"] == []
    assert props["st"] == 1
    assert props["sr"] is None
    assert props["tir"] is None
    assert props["ss"] == 0
    assert props["sp"] is None


def test_task_update_with_project_target_only_writes_container_fields() -> None:
    change_map = build_task_update(
        "TASK_ID",
        timezone="Asia/Shanghai",
        project_id="PROJECT_ID",
        current_state={"st": 0, "ss": 0},
    )
    props = change_map["TASK_ID"]["p"]

    assert props["pr"] == ["PROJECT_ID"]
    assert props["ar"] == []
    assert props["agr"] == []
    assert "st" not in props


def test_task_update_supports_clear_semantics() -> None:
    change_map = build_task_update(
        "TASK_ID",
        timezone="Asia/Shanghai",
        notes="",
        when=None,
        deadline=None,
        tag_ids=[],
    )
    props = change_map["TASK_ID"]["p"]

    assert props["nt"]["v"] == ""
    assert props["sr"] is None
    assert props["tir"] is None
    assert props["st"] == 0
    assert props["ato"] is None
    assert props["dd"] is None
    assert props["tg"] == []


def test_task_update_sets_and_clears_reminder_time() -> None:
    change_map = build_task_update(
        "TASK_ID",
        timezone="Asia/Shanghai",
        reminder_time="15:20",
        current_state={"sr": 1777075200, "tir": 1777075200},
    )
    props = change_map["TASK_ID"]["p"]
    assert props["ato"] == 55200
    assert "rmd" not in props

    clear_map = build_task_update("TASK_ID", timezone="Asia/Shanghai", reminder_time=None)
    assert clear_map["TASK_ID"]["p"]["ato"] is None


def test_task_update_rejects_reminder_time_without_scheduled_date() -> None:
    with pytest.raises(ValueError, match="When date"):
        build_task_update("TASK_ID", timezone="Asia/Shanghai", reminder_time="09:00")


def test_task_placement_targets_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="exactly one direct placement target"):
        build_task_placement_props(project_id="PROJECT", list_name="inbox")


def test_build_update_complete_cancel_delete_payloads() -> None:
    update = build_task_update("task-id", timezone="Asia/Shanghai", title="New", tag_ids=["a", "a"])
    assert update["task-id"]["p"]["tt"] == "New"
    assert update["task-id"]["p"]["tg"] == ["a"]

    complete = build_task_complete("task-id")
    assert complete["task-id"]["p"]["ss"] == STATUS_COMPLETE

    cancel = build_task_cancel("task-id")
    assert cancel["task-id"]["p"]["ss"] == STATUS_CANCEL

    delete = build_task_delete("task-id")
    assert delete["task-id"]["p"]["tr"] is True


def test_project_builders_cover_create_update_status_and_delete() -> None:
    entity_id, create = build_project_create(
        "Project",
        timezone="Asia/Shanghai",
        notes="Notes",
        area_ids=["AREA_1", "AREA_1"],
        tag_ids=["TAG_1", "TAG_2", "TAG_1"],
        when="tomorrow",
        deadline="today",
    )
    create_props = create[entity_id]["p"]
    assert create_props["tp"] == 1
    assert create_props["ar"] == ["AREA_1"]
    assert create_props["tg"] == ["TAG_1", "TAG_2"]
    assert create_props["st"] == 2

    update = build_project_update(
        "PROJECT_ID",
        timezone="Asia/Shanghai",
        title="Renamed",
        notes="",
        area_ids=["AREA_1", "AREA_2", "AREA_1"],
        tag_ids=["TAG_1", "TAG_1"],
        when=None,
        deadline=None,
    )
    update_props = update["PROJECT_ID"]["p"]
    assert update_props["tt"] == "Renamed"
    assert update_props["nt"]["v"] == ""
    assert update_props["ar"] == ["AREA_1", "AREA_2"]
    assert update_props["tg"] == ["TAG_1"]
    assert update_props["st"] == 1
    assert update_props["sr"] is None
    assert update_props["dd"] is None

    status_change = build_project_status_change("PROJECT_ID", STATUS_COMPLETE, ["CHILD_A", "CHILD_B"])
    assert list(status_change.keys()) == ["PROJECT_ID", "CHILD_A", "CHILD_B"]
    assert status_change["CHILD_A"]["p"]["ss"] == STATUS_COMPLETE

    delete = build_project_delete("PROJECT_ID")
    assert delete["PROJECT_ID"]["p"]["tr"] is True
    assert delete["PROJECT_ID"]["p"]["ar"] == []


def test_project_update_rejects_noop() -> None:
    with pytest.raises(ValueError, match="No changes"):
        build_project_update("PROJECT_ID", timezone="Asia/Shanghai")


def test_collect_unfinished_project_task_ids_includes_heading_children_only_when_active() -> None:
    state = {
        "PROJECT_ID": {"id": "PROJECT_ID", "tp": 1},
        "OTHER_PROJECT": {"id": "OTHER_PROJECT", "tp": 1},
        "HEADING_ID": {"id": "HEADING_ID", "tp": 2, "pr": ["PROJECT_ID"]},
        "DELETED_HEADING": {"id": "DELETED_HEADING", "tp": 2, "pr": ["PROJECT_ID"], "deleted": True},
        "TRASHED_HEADING": {"id": "TRASHED_HEADING", "tp": 2, "pr": ["PROJECT_ID"], "tr": True},
        "DIRECT_TASK": {"id": "DIRECT_TASK", "tp": 0, "pr": ["PROJECT_ID"], "ss": 0},
        "HEADING_CHILD": {"id": "HEADING_CHILD", "tp": 0, "agr": ["HEADING_ID"], "ss": 0},
        "DONE": {"id": "DONE", "tp": 0, "pr": ["PROJECT_ID"], "ss": STATUS_COMPLETE},
    }

    assert collect_unfinished_project_task_ids(state, "PROJECT_ID") == ["DIRECT_TASK", "HEADING_CHILD"]


def test_collect_active_project_heading_ids_ignores_trashed_headings() -> None:
    state = {
        "HEADING_A": {"id": "HEADING_A", "tp": 2, "pr": ["PROJECT_ID"]},
        "HEADING_B": {"id": "HEADING_B", "tp": 2, "pr": ["PROJECT_ID"], "tr": True},
        "HEADING_C": {"id": "HEADING_C", "tp": 2, "pr": ["OTHER_PROJECT"]},
    }

    assert collect_active_project_heading_ids(state, "PROJECT_ID") == ["HEADING_A"]


def test_heading_area_and_tag_builders() -> None:
    heading_id, heading_create = build_heading_create("Heading", "PROJECT_ID")
    assert heading_create[heading_id]["p"]["pr"] == ["PROJECT_ID"]

    heading_update = build_heading_update(
        "HEADING_ID",
        title="Renamed",
        notes="Updated notes",
        project_id="PROJECT_ID",
        tag_ids=["TAG_1", "TAG_1"],
    )
    heading_props = heading_update["HEADING_ID"]["p"]
    assert heading_props["tt"] == "Renamed"
    assert heading_props["nt"]["v"] == "Updated notes"
    assert heading_props["pr"] == ["PROJECT_ID"]
    assert heading_props["tg"] == ["TAG_1"]

    area_id, area_create = build_area_create("Area", tag_ids=["TAG_1", "TAG_1"])
    assert area_create[area_id]["p"]["tg"] == ["TAG_1"]

    area_update = build_area_update("AREA_ID", title="New Area", tag_ids=[])
    assert area_update["AREA_ID"]["p"] == {"tt": "New Area", "tg": []}
    assert build_area_delete("AREA_ID") == {"AREA_ID": {"t": 2, "e": "Area3", "p": {}}}

    tag_id, tag_create = build_tag_create("Tag", parent_id="PARENT_ID")
    assert tag_create[tag_id]["p"]["pn"] == ["PARENT_ID"]

    tag_update = build_tag_update("TAG_ID", title="Renamed Tag", clear_parent=True)
    assert tag_update["TAG_ID"]["p"] == {"tt": "Renamed Tag", "pn": []}
    assert build_tag_delete("TAG_ID") == {"TAG_ID": {"t": 2, "e": "Tag4", "p": {}}}


def test_tag_update_rejects_conflicting_parent_options() -> None:
    with pytest.raises(ValueError, match="either parent_id or clear_parent"):
        build_tag_update("TAG_ID", parent_id="PARENT_ID", clear_parent=True)


def test_heading_update_rejects_noop() -> None:
    with pytest.raises(ValueError, match="No changes"):
        build_heading_update("HEADING_ID")


def test_area_update_rejects_noop() -> None:
    with pytest.raises(ValueError, match="No changes"):
        build_area_update("AREA_ID")


def test_tag_update_rejects_noop() -> None:
    with pytest.raises(ValueError, match="No changes"):
        build_tag_update("TAG_ID", parent_id=UNSET)


def test_validate_area_and_tag_state_reject_trashed_entities() -> None:
    state = {
        "AREA_ID": {"id": "AREA_ID", "e": "Area3", "tr": True},
        "TAG_ID": {"id": "TAG_ID", "e": "Tag4", "tr": True},
    }

    with pytest.raises(ValueError, match="Area not found"):
        validate_area_state(state, "AREA_ID")
    with pytest.raises(ValueError, match="Tag not found"):
        validate_tag_state(state, "TAG_ID")
