from __future__ import annotations

from typing import Any

import pytest

from things_mcp import cloud_client
from things_mcp import service as service_module
from things_mcp.cloud_client import ConfigError, ThingsCloudClient, ThingsConfig, ThingsCloudError
from things_mcp.service import ThingsService
from things_mcp.store import EntityStore


class FakeClient:
    def __init__(self) -> None:
        self.history_calls = 0
        self.commit_calls = 0
        self.commits: list[tuple[dict[str, Any], int, int]] = []

    def history(self) -> dict[str, Any]:
        self.history_calls += 1
        return {"latest-server-index": 10 + self.history_calls, "latest-schema-version": 301}

    def history_items(self, start_index: int = 0) -> dict[str, Any]:
        return {"current-item-index": start_index + 1, "items": [{"task": {"t": 1, "e": "Task6", "p": {}}}]}

    def commit(self, change_map: dict[str, Any], ancestor_index: int, schema: int) -> dict[str, Any]:
        self.commit_calls += 1
        self.commits.append((change_map, ancestor_index, schema))
        return {"things-response": "OK"}


class RetryClient(FakeClient):
    def commit(self, change_map: dict[str, Any], ancestor_index: int, schema: int) -> dict[str, Any]:
        self.commit_calls += 1
        self.commits.append((change_map, ancestor_index, schema))
        if self.commit_calls == 1:
            raise ThingsCloudError("ancestor index conflict", status=409)
        return {"things-response": "OK"}


class SyncClient:
    def __init__(self) -> None:
        self.fail = False
        self.history_item_calls: list[int] = []
        self.config = ThingsConfig(email="e", password="p", history_key="h", timezone="Asia/Shanghai")

    def history(self) -> dict[str, Any]:
        if self.fail:
            raise ThingsCloudError("offline")
        return {"latest-server-index": 10, "latest-schema-version": 301}

    def history_items(self, start_index: int = 0) -> dict[str, Any]:
        if self.fail:
            raise ThingsCloudError("offline")
        self.history_item_calls.append(start_index)
        if start_index == 0:
            return {
                "current-item-index": 1,
                "items": [
                    {
                        "task": {
                            "t": 0,
                            "e": "Task6",
                            "p": {
                                "tp": 0,
                                "tt": "Cached task",
                                "ss": 0,
                                "tr": False,
                                "cd": 1776823200,
                                "md": 1.0,
                                "sr": 1776816000,
                                "dd": 1776902400,
                            },
                        }
                    }
                ],
            }
        return {"current-item-index": start_index, "items": []}


class PartialSyncClient:
    def __init__(self) -> None:
        self.config = ThingsConfig(email="e", password="p", history_key="h", timezone="Asia/Shanghai")
        self.history_item_calls: list[int] = []

    def history(self) -> dict[str, Any]:
        return {"latest-server-index": 10, "latest-schema-version": 301}

    def history_items(self, start_index: int = 0) -> dict[str, Any]:
        self.history_item_calls.append(start_index)
        if start_index == 0:
            return {
                "current-item-index": 2,
                "items": [
                    {
                        "partial-task": {
                            "t": 0,
                            "e": "Task6",
                            "p": {"tp": 0, "tt": "Partial", "ss": 0, "tr": False},
                        }
                    }
                ],
            }
        raise ThingsCloudError("page fetch failed")


class DomainStateClient:
    def __init__(self) -> None:
        self.config = ThingsConfig(email="e", password="p", history_key="h", timezone="Asia/Shanghai")
        self.history_item_calls: list[int] = []
        self.commits: list[tuple[dict[str, Any], int, int]] = []
        self.items = [
            {"project": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Project", "ss": 0, "tr": False}}},
            {"other-project": {"t": 0, "e": "Task6", "p": {"tp": 1, "tt": "Other", "ss": 0, "tr": False}}},
            {"heading": {"t": 0, "e": "Task6", "p": {"tp": 2, "tt": "Heading", "pr": ["project"], "ss": 0, "tr": False}}},
            {"task": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Task", "pr": ["project"], "ss": 0, "tr": False}}},
            {"logged-task": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Logged", "ss": 3, "tr": False, "st": 1, "sr": None, "tir": None}}},
            {"heading-child": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Child", "agr": ["heading"], "ss": 0, "tr": False}}},
            {"done-child": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Done", "pr": ["project"], "ss": 3, "tr": False}}},
            {"area": {"t": 0, "e": "Area3", "p": {"tt": "Area"}}},
            {"tag": {"t": 0, "e": "Tag4", "p": {"tt": "Tag"}}},
            {"parent-tag": {"t": 0, "e": "Tag4", "p": {"tt": "Parent"}}},
        ]

    def history(self) -> dict[str, Any]:
        return {"latest-server-index": 10, "latest-schema-version": 301}

    def history_items(self, start_index: int = 0) -> dict[str, Any]:
        self.history_item_calls.append(start_index)
        if start_index == 0:
            return {"current-item-index": len(self.items), "items": list(self.items)}
        return {"current-item-index": len(self.items), "items": []}

    def commit(self, change_map: dict[str, Any], ancestor_index: int, schema: int) -> dict[str, Any]:
        self.commits.append((change_map, ancestor_index, schema))
        return {"things-response": "OK"}


def test_write_dry_run_does_not_commit() -> None:
    client = FakeClient()
    service = ThingsService(client)  # type: ignore[arg-type]

    result = service.write(lambda: ("task", {"task": {"t": 1, "e": "Task6", "p": {}}}), dry_run=True)

    assert result["dry_run"] is True
    assert result["entity_id"] == "task"
    assert client.commit_calls == 0


def test_write_commit_success() -> None:
    client = FakeClient()
    service = ThingsService(client)  # type: ignore[arg-type]

    result = service.write(lambda: ("task", {"task": {"t": 1, "e": "Task6", "p": {}}}))

    assert result["dry_run"] is False
    assert result["verify"]["items_count"] == 1
    assert client.commits[0][1] == 11


def test_write_retries_index_conflict_once() -> None:
    client = RetryClient()
    service = ThingsService(client)  # type: ignore[arg-type]

    service.write(lambda: ("task", {"task": {"t": 1, "e": "Task6", "p": {}}}))

    assert client.commit_calls == 2
    assert [commit[1] for commit in client.commits] == [11, 12]


def test_write_does_not_retry_non_conflict_error() -> None:
    class BadClient(FakeClient):
        def commit(self, change_map: dict[str, Any], ancestor_index: int, schema: int) -> dict[str, Any]:
            raise ThingsCloudError("auth failed", status=401)

    service = ThingsService(BadClient())  # type: ignore[arg-type]
    with pytest.raises(ThingsCloudError):
        service.write(lambda: ("task", {"task": {"t": 1, "e": "Task6", "p": {}}}))


def test_read_syncs_to_store_before_query(tmp_path) -> None:
    client = SyncClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    first = service.list_todos()
    second = service.list_todos()

    assert [item["id"] for item in first.data] == ["task"]
    assert second.data == first.data
    assert first.stale is False
    assert client.history_item_calls == [0, 1]


def test_read_sync_respects_ttl(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("THINGS_MCP_SYNC_TTL_SECONDS", "60")
    client = SyncClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    service.list_todos()
    service.list_todos()

    assert client.history_item_calls == [0]


def test_partial_sync_failure_does_not_refresh_ttl(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("THINGS_MCP_SYNC_TTL_SECONDS", "60")
    monkeypatch.setattr(service_module, "HISTORY_ITEMS_BATCH_SIZE", 1)
    client = PartialSyncClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    first = service.list_todos()
    second = service.list_todos()

    assert [item["id"] for item in first.data] == ["partial-task"]
    assert first.stale is True
    assert second.stale is True
    assert client.history_item_calls == [0, 1, 1]


def test_service_validates_status_limit_query_and_title(tmp_path) -> None:
    service = ThingsService(SyncClient(), EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Invalid status"):
        service.list_todos(status="bogus")
    with pytest.raises(ValueError, match="limit"):
        service.list_todos(limit=501)
    with pytest.raises(ValueError, match="query"):
        service.search_todos(query=" ")
    with pytest.raises(ValueError, match="title"):
        service.create_todo(title=" ", dry_run=True)


def test_change_map_logs_are_redacted_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THINGS_MCP_LOG_PAYLOADS", raising=False)

    logged = service_module._log_change_map({"task": {"p": {"tt": "Secret"}}})

    assert logged == {"redacted": True, "entity_count": 1, "entity_ids": ["task"]}


def test_list_todos_filters_start_and_deadline_dates(tmp_path) -> None:
    client = SyncClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    result = service.list_todos(start_from="2026-04-22", start_to="2026-04-22", deadline_to="2026-04-23")

    assert [item["id"] for item in result.data] == ["task"]


def test_list_todos_filters_created_date_for_full_day(tmp_path) -> None:
    client = SyncClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    result = service.list_todos(created_from="2026-04-22", created_to="2026-04-22")

    assert [item["id"] for item in result.data] == ["task"]


def test_list_todos_filters_things_date_fields_for_utc_midnight_encoding(tmp_path) -> None:
    client = SyncClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    result = service.list_todos(start_from="2026-04-22", start_to="2026-04-22", deadline_to="2026-04-23")

    assert [item["id"] for item in result.data] == ["task"]


def test_list_todos_excludes_dates_outside_range(tmp_path) -> None:
    client = SyncClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    result = service.list_todos(start_from="2026-04-23")

    assert result.data == []


def test_read_returns_stale_cache_when_sync_fails_after_cache_exists(tmp_path) -> None:
    client = SyncClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]
    service.list_todos()

    client.fail = True
    result = service.list_todos()

    assert [item["id"] for item in result.data] == ["task"]
    assert result.stale is True
    assert result.sync_error == "offline"


def test_read_raises_sync_error_when_no_cache_exists(tmp_path) -> None:
    client = SyncClient()
    client.fail = True
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    with pytest.raises(ThingsCloudError):
        service.list_todos()


def test_write_commit_success_syncs_store_when_configured(tmp_path) -> None:
    class WriteSyncClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.history_item_calls: list[int] = []

        def history_items(self, start_index: int = 0) -> dict[str, Any]:
            self.history_item_calls.append(start_index)
            if start_index == 0:
                return {
                    "current-item-index": 1,
                    "items": [
                        {"task": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Created", "ss": 0, "tr": False}}}
                    ],
                }
            return {"current-item-index": start_index, "items": []}

    client = WriteSyncClient()
    store = EntityStore(tmp_path / "entities.sqlite")
    service = ThingsService(client, store)  # type: ignore[arg-type]

    result = service.write(lambda: ("task", {"task": {"t": 1, "e": "Task6", "p": {}}}))

    assert result["dry_run"] is False
    assert client.history_item_calls == [11, 0]
    assert store.load_state()["task"]["tt"] == "Created"


def test_state_aware_create_todo_dry_run_uses_validated_targets(tmp_path) -> None:
    client = DomainStateClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    result = service.create_todo(
        title="New task",
        when="2026-04-25",
        reminder_time="04:15",
        project_id="project",
        tag_ids=["tag"],
        checklist_items=["one"],
        dry_run=True,
    )

    created_id = result["entity_id"]
    props = result["change_map"][created_id]["p"]
    assert props["pr"] == ["project"]
    assert props["tg"] == ["tag"]
    assert props["ato"] == 15300
    assert any(item["e"] == "ChecklistItem3" for key, item in result["change_map"].items() if key != created_id)
    assert client.commits == []


def test_state_aware_update_todo_sets_reminder_time_with_when(tmp_path) -> None:
    client = DomainStateClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    result = service.update_todo(
        entity_id="task",
        when="2026-04-25",
        reminder_time="04:15",
        dry_run=True,
    )

    props = result["change_map"]["task"]["p"]
    assert props["sr"] == 1777075200
    assert props["tir"] == 1777075200
    assert props["ato"] == 15300


def test_state_aware_update_todo_supports_clear_and_reopen_from_logbook(tmp_path) -> None:
    client = DomainStateClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    result = service.update_todo(
        entity_id="logged-task",
        list_name="anytime",
        clear_tags=True,
        clear_notes=True,
        clear_deadline=True,
        dry_run=True,
    )

    props = result["change_map"]["logged-task"]["p"]
    assert props["ss"] == 0
    assert props["sp"] is None
    assert props["st"] == 1
    assert props["sr"] is None
    assert props["tir"] is None
    assert props["tg"] == []
    assert props["nt"]["v"] == ""
    assert props["dd"] is None


def test_state_aware_update_todo_rejects_conflicting_clear_flags(tmp_path) -> None:
    client = DomainStateClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="clear_tags"):
        service.update_todo(entity_id="task", tag_ids=["tag"], clear_tags=True, dry_run=True)


def test_state_aware_update_project_clear_fields(tmp_path) -> None:
    client = DomainStateClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    result = service.update_project(
        entity_id="project",
        clear_notes=True,
        clear_when=True,
        clear_deadline=True,
        clear_area=True,
        clear_tags=True,
        dry_run=True,
    )

    props = result["change_map"]["project"]["p"]
    assert props["nt"]["v"] == ""
    assert props["st"] == 1
    assert props["sr"] is None
    assert props["tir"] is None
    assert props["dd"] is None
    assert props["ar"] == []
    assert props["tg"] == []


def test_complete_project_cascades_unfinished_children(tmp_path) -> None:
    client = DomainStateClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    result = service.complete_project(entity_id="project", dry_run=True)

    change_map = result["change_map"]
    assert list(change_map.keys()) == ["project", "heading", "heading-child", "task"]
    assert all(entry["p"]["ss"] == 3 for entry in change_map.values())


def test_list_headings_filters_project(tmp_path) -> None:
    client = DomainStateClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    result = service.list_headings(project_id="project")

    assert [item["id"] for item in result.data] == ["heading"]


def test_convenience_read_methods(tmp_path) -> None:
    client = DomainStateClient()
    client.items.extend(
        [
            {"inbox-task": {"t": 0, "e": "Task6", "p": {"tp": 0, "tt": "Inbox", "ss": 0, "tr": False, "st": 0}}},
            {
                "upcoming-task": {
                        "t": 0,
                        "e": "Task6",
                        "p": {"tp": 0, "tt": "Upcoming", "ss": 0, "tr": False, "st": 2, "sr": 1777161600, "tir": 1777161600},
                    }
                },
                {
                    "deadline-task": {
                        "t": 0,
                        "e": "Task6",
                        "p": {"tp": 0, "tt": "Deadline", "ss": 0, "tr": False, "pr": ["project"], "dd": 1777161600},
                    }
                },
        ]
    )
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    assert [item["id"] for item in service.list_inbox_todos().data] == ["inbox-task"]
    assert [item["id"] for item in service.list_upcoming_todos(start_from="2026-04-26", start_to="2026-04-26").data] == [
        "upcoming-task"
    ]
    assert [item["id"] for item in service.list_deadline_todos(deadline_to="2026-04-26").data] == ["deadline-task"]
    assert {item["id"] for item in service.list_logbook_todos().data} >= {"logged-task", "done-child"}
    assert [item["id"] for item in service.search_projects(query="project").data] == ["project"]
    assert [item["id"] for item in service.search_tags(query="tag").data] == ["tag"]


def test_state_aware_validates_entity_types(tmp_path) -> None:
    client = DomainStateClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="regular task"):
        service.complete_todo(entity_id="project", dry_run=True)


def test_state_aware_rejects_trashed_heading_updates(tmp_path) -> None:
    client = DomainStateClient()
    client.items.append(
        {"trashed-heading": {"t": 0, "e": "Task6", "p": {"tp": 2, "tt": "Heading", "pr": ["project"], "ss": 0, "tr": True}}}
    )
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Heading not found"):
        service.update_heading(entity_id="trashed-heading", title="Renamed", dry_run=True)


def test_state_aware_tag_operations_validate_parent(tmp_path) -> None:
    client = DomainStateClient()
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    create = service.create_tag(title="Child", parent_id="parent-tag", dry_run=True)
    created_id = create["entity_id"]
    assert create["change_map"][created_id]["p"]["pn"] == ["parent-tag"]

    update = service.update_tag(entity_id="tag", parent_id="parent-tag", dry_run=True)
    assert update["change_map"]["tag"]["p"]["pn"] == ["parent-tag"]


def test_state_aware_rejects_trashed_area_and_tag_targets(tmp_path) -> None:
    client = DomainStateClient()
    client.items.extend(
        [
            {"trashed-area": {"t": 0, "e": "Area3", "p": {"tt": "Area", "tr": True}}},
            {"trashed-tag": {"t": 0, "e": "Tag4", "p": {"tt": "Tag", "tr": True}}},
        ]
    )
    service = ThingsService(client, EntityStore(tmp_path / "entities.sqlite"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Area not found"):
        service.create_todo(title="Task", area_id="trashed-area", dry_run=True)
    with pytest.raises(ValueError, match="Tag not found"):
        service.create_todo(title="Task", tag_ids=["trashed-tag"], dry_run=True)


def test_write_headers_include_real_client_metadata_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cloud_client,
        "detect_things_client_headers",
        lambda: {"User-Agent": "ThingsMac/123", "things-client-info": "encoded"},
    )
    monkeypatch.setattr(cloud_client, "detect_app_instance_id", lambda app_id: "instance-id")
    client = ThingsCloudClient(ThingsConfig(email="e", password="p", history_key="h"))

    headers = client._write_headers(301)

    assert headers["Schema"] == "301"
    assert headers["App-Id"] == "com.culturedcode.ThingsMac"
    assert headers["App-Instance-Id"] == "instance-id"
    assert headers["User-Agent"] == "ThingsMac/123"
    assert headers["things-client-info"] == "encoded"


def test_write_headers_allow_env_app_instance_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cloud_client, "detect_things_client_headers", lambda: None)
    monkeypatch.setattr(cloud_client, "detect_app_instance_id", lambda app_id: "detected-id")
    config = ThingsConfig(email="e", password="p", history_key="h", app_instance_id="configured-id")
    client = ThingsCloudClient(config)

    headers = client._write_headers(301)

    assert headers["App-Instance-Id"] == "configured-id"
    assert headers["User-Agent"] == "ThingsMCP/0.1.0"


def test_config_validates_timezone_and_push_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THINGS_CLOUD_EMAIL", "e")
    monkeypatch.setenv("THINGS_CLOUD_PASSWORD", "p")
    monkeypatch.setenv("THINGS_CLOUD_HISTORY_KEY", "h")
    monkeypatch.setenv("THINGS_TIMEZONE", "Not/AZone")

    with pytest.raises(ConfigError, match="THINGS_TIMEZONE"):
        ThingsConfig.from_env()

    monkeypatch.setenv("THINGS_TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("THINGS_MCP_PUSH_PRIORITY", "11")

    with pytest.raises(ConfigError, match="PUSH_PRIORITY"):
        ThingsConfig.from_env()


def test_config_defaults_to_utc_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THINGS_CLOUD_EMAIL", "e")
    monkeypatch.setenv("THINGS_CLOUD_PASSWORD", "p")
    monkeypatch.setenv("THINGS_CLOUD_HISTORY_KEY", "h")
    monkeypatch.delenv("THINGS_TIMEZONE", raising=False)

    assert ThingsConfig.from_env().timezone == "UTC"
