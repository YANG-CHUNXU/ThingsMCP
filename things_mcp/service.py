from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from .cloud_client import ThingsCloudClient, ThingsCloudError, ThingsConfig
from .history import (
    HISTORY_ITEMS_BATCH_SIZE,
    areas,
    deadline_todos,
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
from .mutations import (
    UNSET,
    build_area_create,
    build_area_delete,
    build_area_update,
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
    build_task_update,
    collect_active_project_heading_ids,
    collect_unfinished_project_task_ids,
    parse_local_date,
    validate_area_ids,
    validate_area_state,
    validate_heading_state,
    validate_project_state,
    validate_tag_ids,
    validate_tag_state,
    validate_task_state,
)
from .store import EntityStore


logger = logging.getLogger("things_mcp.service")

MAX_LIMIT = 500
TODO_PROJECT_STATUSES = {"open", "archived", "completed", "trashed", "deleted", "all"}
AREA_TAG_STATUSES = {"open", "trashed", "deleted", "all"}


@dataclass(frozen=True)
class ReadResult:
    data: Any
    stale: bool = False
    sync_error: str | None = None


class ThingsService:
    def __init__(self, client: ThingsCloudClient, store: EntityStore | None = None) -> None:
        self.client = client
        self.store = store
        self._sync_lock = Lock()

    @classmethod
    def from_env(cls) -> "ThingsService":
        return cls(ThingsCloudClient(ThingsConfig.from_env()), EntityStore.from_env())

    def list_todos(
        self,
        *,
        status: str = "open",
        project_id: str | None = None,
        area_id: str | None = None,
        tag_ids: list[str] | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        start_from: str | None = None,
        start_to: str | None = None,
        deadline_from: str | None = None,
        deadline_to: str | None = None,
        limit: int = 100,
    ) -> ReadResult:
        status = validate_status(status, TODO_PROJECT_STATUSES, "status")
        limit = validate_limit(limit)
        timezone = self._timezone()
        created_from_at = parse_local_date(created_from, timezone)
        created_to_at = _parse_local_date_end(created_to, timezone)
        start_from_at = _parse_things_date_start(start_from, timezone)
        start_to_at = _parse_things_date_end(start_to, timezone)
        deadline_from_at = _parse_things_date_start(deadline_from, timezone)
        deadline_to_at = _parse_things_date_end(deadline_to, timezone)
        return self._read_todos(
            lambda store: store.list_todos(
                status=status,
                project_id=project_id,
                area_id=area_id,
                tag_ids=tag_ids,
                created_from=created_from_at,
                created_to=created_to_at,
                start_from=start_from_at,
                start_to=start_to_at,
                deadline_from=deadline_from_at,
                deadline_to=deadline_to_at,
                limit=limit,
            ),
            lambda state: todos(
                state,
                status=status,
                project_id=project_id,
                area_id=area_id,
                tag_ids=tag_ids,
                created_from=created_from_at,
                created_to=created_to_at,
                start_from=start_from_at,
                start_to=start_to_at,
                deadline_from=deadline_from_at,
                deadline_to=deadline_to_at,
                limit=limit,
            ),
        )

    def list_inbox_todos(self, *, tag_ids: list[str] | None = None, limit: int = 100) -> ReadResult:
        limit = validate_limit(limit)
        return self._read(lambda state: inbox_todos(state, tag_ids=tag_ids, limit=limit))

    def list_upcoming_todos(
        self,
        *,
        start_from: str | None = "tomorrow",
        start_to: str | None = None,
        tag_ids: list[str] | None = None,
        limit: int = 100,
    ) -> ReadResult:
        return self.list_todos(
            status="open",
            tag_ids=tag_ids,
            start_from=start_from,
            start_to=start_to,
            limit=limit,
        )

    def list_deadline_todos(
        self,
        *,
        deadline_from: str | None = None,
        deadline_to: str | None = None,
        tag_ids: list[str] | None = None,
        limit: int = 100,
    ) -> ReadResult:
        limit = validate_limit(limit)
        timezone = self._timezone()
        deadline_from_at = _parse_things_date_start(deadline_from, timezone)
        deadline_to_at = _parse_things_date_end(deadline_to, timezone)
        return self._read(
            lambda state: deadline_todos(
                state,
                tag_ids=tag_ids,
                deadline_from=deadline_from_at,
                deadline_to=deadline_to_at,
                limit=limit,
            )
        )

    def list_logbook_todos(self, *, limit: int = 100) -> ReadResult:
        return self.list_todos(status="archived", limit=limit)

    def search_todos(
        self,
        *,
        query: str,
        status: str = "all",
        created_from: str | None = None,
        created_to: str | None = None,
        deadline_from: str | None = None,
        deadline_to: str | None = None,
        limit: int = 100,
    ) -> ReadResult:
        query = validate_query(query)
        status = validate_status(status, TODO_PROJECT_STATUSES, "status")
        limit = validate_limit(limit)
        timezone = self._timezone()
        created_from_at = parse_local_date(created_from, timezone)
        created_to_at = _parse_local_date_end(created_to, timezone)
        deadline_from_at = _parse_things_date_start(deadline_from, timezone)
        deadline_to_at = _parse_things_date_end(deadline_to, timezone)
        return self._read(
            lambda state: search_todos(
                state,
                query,
                status=status,
                created_from=created_from_at,
                created_to=created_to_at,
                deadline_from=deadline_from_at,
                deadline_to=deadline_to_at,
                limit=limit,
            )
        )

    def search_projects(self, *, query: str, status: str = "all", limit: int = 100) -> ReadResult:
        query = validate_query(query)
        status = validate_status(status, TODO_PROJECT_STATUSES, "status")
        limit = validate_limit(limit)
        return self._read(lambda state: search_projects(state, query, status=status, limit=limit))

    def search_tags(self, *, query: str, status: str = "all", limit: int = 100) -> ReadResult:
        query = validate_query(query)
        status = validate_status(status, AREA_TAG_STATUSES, "status")
        limit = validate_limit(limit)
        return self._read(lambda state: search_tags(state, query, status=status, limit=limit))

    def get_item(self, *, entity_id: str) -> ReadResult:
        return self._read(lambda state: get_item(state, entity_id))

    def list_projects(
        self,
        *,
        status: str = "open",
        created_from: str | None = None,
        created_to: str | None = None,
        deadline_from: str | None = None,
        deadline_to: str | None = None,
        limit: int = 100,
    ) -> ReadResult:
        status = validate_status(status, TODO_PROJECT_STATUSES, "status")
        limit = validate_limit(limit)
        timezone = self._timezone()
        created_from_at = parse_local_date(created_from, timezone)
        created_to_at = _parse_local_date_end(created_to, timezone)
        deadline_from_at = _parse_things_date_start(deadline_from, timezone)
        deadline_to_at = _parse_things_date_end(deadline_to, timezone)
        return self._read(
            lambda state: projects(
                state,
                status=status,
                created_from=created_from_at,
                created_to=created_to_at,
                deadline_from=deadline_from_at,
                deadline_to=deadline_to_at,
                limit=limit,
            )
        )

    def list_headings(self, *, project_id: str | None = None, limit: int = 100) -> ReadResult:
        limit = validate_limit(limit)
        return self._read(lambda state: headings(state, project_id=project_id, limit=limit))

    def list_areas(
        self,
        *,
        status: str = "open",
        created_from: str | None = None,
        created_to: str | None = None,
        limit: int = 100,
    ) -> ReadResult:
        status = validate_status(status, AREA_TAG_STATUSES, "status")
        limit = validate_limit(limit)
        timezone = self._timezone()
        created_from_at = parse_local_date(created_from, timezone)
        created_to_at = _parse_local_date_end(created_to, timezone)
        return self._read(
            lambda state: areas(
                state,
                status=status,
                created_from=created_from_at,
                created_to=created_to_at,
                limit=limit,
            )
        )

    def list_tags(
        self,
        *,
        status: str = "open",
        created_from: str | None = None,
        created_to: str | None = None,
        limit: int = 100,
    ) -> ReadResult:
        status = validate_status(status, AREA_TAG_STATUSES, "status")
        limit = validate_limit(limit)
        timezone = self._timezone()
        created_from_at = parse_local_date(created_from, timezone)
        created_to_at = _parse_local_date_end(created_to, timezone)
        return self._read(
            lambda state: tags(
                state,
                status=status,
                created_from=created_from_at,
                created_to=created_to_at,
                limit=limit,
            )
        )

    def create_todo(
        self,
        *,
        title: str,
        notes: str = "",
        when: str | None = None,
        reminder_time: str | None = None,
        deadline: str | None = None,
        tag_ids: list[str] | None = None,
        checklist_items: list[str] | None = None,
        project_id: str | None = None,
        area_id: str | None = None,
        list_name: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        timezone = self._timezone()
        return self.write_with_state(
            lambda state: self._create_todo_builder(
                state,
                title=title,
                timezone=timezone,
                notes=notes,
                when=when,
                reminder_time=reminder_time,
                deadline=deadline,
                tag_ids=tag_ids,
                checklist_items=checklist_items,
                project_id=project_id,
                area_id=area_id,
                list_name=list_name,
            ),
            dry_run=dry_run,
        )

    def update_todo(
        self,
        *,
        entity_id: str,
        title: str | None = None,
        notes: str | None = None,
        clear_notes: bool = False,
        when: str | None = None,
        clear_when: bool = False,
        reminder_time: str | None = None,
        clear_reminder: bool = False,
        deadline: str | None = None,
        clear_deadline: bool = False,
        tag_ids: list[str] | None = None,
        clear_tags: bool = False,
        project_id: str | None = None,
        area_id: str | None = None,
        list_name: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        timezone = self._timezone()
        return self.write_with_state(
            lambda state: self._update_todo_builder(
                state,
                entity_id=entity_id,
                timezone=timezone,
                title=title,
                notes=self._resolve_clearable("notes", notes, clear_notes),
                when=self._resolve_clearable("when", when, clear_when),
                reminder_time=self._resolve_clearable("reminder", reminder_time, clear_reminder),
                deadline=self._resolve_clearable("deadline", deadline, clear_deadline),
                tag_ids=self._resolve_clearable_list("tags", tag_ids, clear_tags),
                project_id=project_id,
                area_id=area_id,
                list_name=list_name,
            ),
            dry_run=dry_run,
        )

    def complete_todo(self, *, entity_id: str, dry_run: bool = False) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: self._simple_task_write(state, entity_id, build_task_complete),
            dry_run=dry_run,
        )

    def cancel_todo(self, *, entity_id: str, dry_run: bool = False) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: self._simple_task_write(state, entity_id, build_task_cancel),
            dry_run=dry_run,
        )

    def delete_todo(self, *, entity_id: str, dry_run: bool = False) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: self._simple_task_write(state, entity_id, build_task_delete),
            dry_run=dry_run,
        )

    def create_project(
        self,
        *,
        title: str,
        notes: str = "",
        when: str | None = None,
        deadline: str | None = None,
        area_ids: list[str] | None = None,
        tag_ids: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        timezone = self._timezone()
        return self.write_with_state(
            lambda state: build_project_create(
                title,
                timezone=timezone,
                notes=notes,
                when=when,
                deadline=deadline,
                area_ids=validate_area_ids(state, area_ids),
                tag_ids=validate_tag_ids(state, tag_ids),
            ),
            dry_run=dry_run,
        )

    def update_project(
        self,
        *,
        entity_id: str,
        title: str | None = None,
        notes: str | None = None,
        clear_notes: bool = False,
        when: str | None = None,
        clear_when: bool = False,
        deadline: str | None = None,
        clear_deadline: bool = False,
        area_ids: list[str] | None = None,
        clear_area: bool = False,
        tag_ids: list[str] | None = None,
        clear_tags: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        timezone = self._timezone()
        return self.write_with_state(
            lambda state: self._update_project_builder(
                state,
                entity_id=entity_id,
                timezone=timezone,
                title=title,
                notes=self._resolve_clearable("notes", notes, clear_notes),
                when=self._resolve_clearable("when", when, clear_when),
                deadline=self._resolve_clearable("deadline", deadline, clear_deadline),
                area_ids=self._resolve_clearable_list("area", area_ids, clear_area),
                tag_ids=self._resolve_clearable_list("tags", tag_ids, clear_tags),
            ),
            dry_run=dry_run,
        )

    def complete_project(self, *, entity_id: str, dry_run: bool = False) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: self._project_status_builder(state, entity_id=entity_id, status_value=3),
            dry_run=dry_run,
        )

    def cancel_project(self, *, entity_id: str, dry_run: bool = False) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: self._project_status_builder(state, entity_id=entity_id, status_value=2),
            dry_run=dry_run,
        )

    def delete_project(self, *, entity_id: str, dry_run: bool = False) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: self._simple_project_write(state, entity_id, build_project_delete),
            dry_run=dry_run,
        )

    def create_heading(self, *, title: str, project_id: str, dry_run: bool = False) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: build_heading_create(title, validate_project_state(state, project_id)["id"]),
            dry_run=dry_run,
        )

    def update_heading(
        self,
        *,
        entity_id: str,
        title: str | None = None,
        notes: str | None = None,
        clear_notes: bool = False,
        project_id: str | None = None,
        tag_ids: list[str] | None = None,
        clear_tags: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: self._update_heading_builder(
                state,
                entity_id=entity_id,
                title=title,
                notes=self._resolve_clearable("notes", notes, clear_notes),
                project_id=project_id,
                tag_ids=self._resolve_clearable_list("tags", tag_ids, clear_tags),
            ),
            dry_run=dry_run,
        )

    def create_area(self, *, title: str, tag_ids: list[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: build_area_create(title, tag_ids=validate_tag_ids(state, tag_ids)),
            dry_run=dry_run,
        )

    def update_area(
        self,
        *,
        entity_id: str,
        title: str | None = None,
        tag_ids: list[str] | None = None,
        clear_tags: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: self._update_area_builder(
                state,
                entity_id=entity_id,
                title=title,
                tag_ids=self._resolve_clearable_list("tags", tag_ids, clear_tags),
            ),
            dry_run=dry_run,
        )

    def delete_area(self, *, entity_id: str, dry_run: bool = False) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: self._simple_area_write(state, entity_id, build_area_delete),
            dry_run=dry_run,
        )

    def create_tag(self, *, title: str, parent_id: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: self._create_tag_builder(state, title=title, parent_id=parent_id),
            dry_run=dry_run,
        )

    def update_tag(
        self,
        *,
        entity_id: str,
        title: str | None = None,
        parent_id: str | None = None,
        clear_parent: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: self._update_tag_builder(
                state,
                entity_id=entity_id,
                title=title,
                parent_id=parent_id,
                clear_parent=clear_parent,
            ),
            dry_run=dry_run,
        )

    def delete_tag(self, *, entity_id: str, dry_run: bool = False) -> dict[str, Any]:
        return self.write_with_state(
            lambda state: self._simple_tag_write(state, entity_id, build_tag_delete),
            dry_run=dry_run,
        )

    def sync_entities(self, *, force: bool = False) -> None:
        store = self._store()
        with self._sync_lock:
            if not force and not should_sync(store):
                return
            history = self.client.history()
            latest_server_index = int(history["latest-server-index"])
            latest_schema_version = int(history.get("latest-schema-version") or 301)
            start_index = store.latest_item_index() or 0

            while True:
                body = self.client.history_items(start_index)
                items = body.get("items") or []
                current_index = int(body.get("current-item-index") or start_index + len(items))
                applied_index = start_index + len(items) if items else current_index
                store.apply_history_items(
                    items,
                    latest_item_index=applied_index,
                    latest_schema_version=latest_schema_version,
                    latest_server_index=latest_server_index,
                    mark_synced=False,
                )
                if not items:
                    store.set_meta("last_synced_at", time.time())
                    return
                start_index = applied_index
                if len(items) < HISTORY_ITEMS_BATCH_SIZE or start_index >= current_index:
                    store.set_meta("last_synced_at", time.time())
                    return

    def write(
        self,
        builder: Callable[[], tuple[str | None, dict[str, Any]]],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        entity_id, change_map = builder()
        return self._commit_change_map(entity_id, change_map, dry_run=dry_run)

    def write_with_state(
        self,
        builder: Callable[[dict[str, dict[str, Any]]], tuple[str | None, dict[str, Any]]],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        state = self._fresh_state()
        entity_id, change_map = builder(state)
        return self._commit_change_map(entity_id, change_map, dry_run=dry_run)

    def _create_todo_builder(
        self,
        state: dict[str, dict[str, Any]],
        *,
        title: str,
        timezone: str,
        notes: str,
        when: str | None,
        reminder_time: str | None,
        deadline: str | None,
        tag_ids: list[str] | None,
        checklist_items: list[str] | None,
        project_id: str | None,
        area_id: str | None,
        list_name: str | None,
    ) -> tuple[str | None, dict[str, Any]]:
        if project_id is not None:
            validate_project_state(state, project_id)
        if area_id is not None:
            validate_area_state(state, area_id)
        valid_tag_ids = validate_tag_ids(state, tag_ids)
        return build_task_create(
            title,
            timezone=timezone,
            notes=notes,
            when=when,
            reminder_time=reminder_time,
            deadline=deadline,
            tag_ids=valid_tag_ids,
            checklist_items=checklist_items,
            project_id=project_id,
            area_id=area_id,
            list_name=list_name,
        )

    def _update_todo_builder(
        self,
        state: dict[str, dict[str, Any]],
        *,
        entity_id: str,
        timezone: str,
        title: str | None,
        notes: str | None | object,
        when: str | None | object,
        reminder_time: str | None | object,
        deadline: str | None | object,
        tag_ids: list[str] | object,
        project_id: str | None,
        area_id: str | None,
        list_name: str | None,
    ) -> tuple[str | None, dict[str, Any]]:
        current_state = validate_task_state(state, entity_id)
        if project_id is not None:
            validate_project_state(state, project_id)
        if area_id is not None:
            validate_area_state(state, area_id)
        valid_tag_ids = tag_ids if tag_ids is UNSET else validate_tag_ids(state, tag_ids if isinstance(tag_ids, list) else [])
        return entity_id, build_task_update(
            entity_id,
            timezone=timezone,
            title=title,
            notes=notes,
            when=when,
            reminder_time=reminder_time,
            deadline=deadline,
            tag_ids=valid_tag_ids,
            project_id=UNSET if project_id is None and area_id is None and list_name is None else project_id,
            area_id=UNSET if project_id is None and area_id is None and list_name is None else area_id,
            list_name=UNSET if list_name is None else list_name,
            current_state=current_state,
        )

    def _update_project_builder(
        self,
        state: dict[str, dict[str, Any]],
        *,
        entity_id: str,
        timezone: str,
        title: str | None,
        notes: str | None | object,
        when: str | None | object,
        deadline: str | None | object,
        area_ids: list[str] | object,
        tag_ids: list[str] | object,
    ) -> tuple[str | None, dict[str, Any]]:
        validate_project_state(state, entity_id)
        valid_area_ids = area_ids if area_ids is UNSET else validate_area_ids(state, area_ids if isinstance(area_ids, list) else [])
        valid_tag_ids = tag_ids if tag_ids is UNSET else validate_tag_ids(state, tag_ids if isinstance(tag_ids, list) else [])
        return entity_id, build_project_update(
            entity_id,
            timezone=timezone,
            title=title,
            notes=notes,
            when=when,
            deadline=deadline,
            area_ids=valid_area_ids,
            tag_ids=valid_tag_ids,
        )

    def _project_status_builder(
        self,
        state: dict[str, dict[str, Any]],
        *,
        entity_id: str,
        status_value: int,
    ) -> tuple[str | None, dict[str, Any]]:
        validate_project_state(state, entity_id)
        heading_ids = collect_active_project_heading_ids(state, entity_id)
        child_task_ids = collect_unfinished_project_task_ids(state, entity_id)
        return entity_id, build_project_status_change(entity_id, status_value, heading_ids + child_task_ids)

    def _update_heading_builder(
        self,
        state: dict[str, dict[str, Any]],
        *,
        entity_id: str,
        title: str | None,
        notes: str | None | object,
        project_id: str | None,
        tag_ids: list[str] | object,
    ) -> tuple[str | None, dict[str, Any]]:
        validate_heading_state(state, entity_id)
        if project_id is not None:
            validate_project_state(state, project_id)
        valid_tag_ids = tag_ids if tag_ids is UNSET else validate_tag_ids(state, tag_ids if isinstance(tag_ids, list) else [])
        return entity_id, build_heading_update(
            entity_id,
            title=title,
            notes=notes,
            project_id=UNSET if project_id is None else project_id,
            tag_ids=valid_tag_ids,
        )

    def _update_area_builder(
        self,
        state: dict[str, dict[str, Any]],
        *,
        entity_id: str,
        title: str | None,
        tag_ids: list[str] | object,
    ) -> tuple[str | None, dict[str, Any]]:
        validate_area_state(state, entity_id)
        valid_tag_ids = tag_ids if tag_ids is UNSET else validate_tag_ids(state, tag_ids if isinstance(tag_ids, list) else [])
        return entity_id, build_area_update(entity_id, title=title, tag_ids=valid_tag_ids)

    def _create_tag_builder(
        self,
        state: dict[str, dict[str, Any]],
        *,
        title: str,
        parent_id: str | None,
    ) -> tuple[str | None, dict[str, Any]]:
        if parent_id is not None:
            validate_tag_state(state, parent_id)
        return build_tag_create(title, parent_id=parent_id)

    def _update_tag_builder(
        self,
        state: dict[str, dict[str, Any]],
        *,
        entity_id: str,
        title: str | None,
        parent_id: str | None,
        clear_parent: bool,
    ) -> tuple[str | None, dict[str, Any]]:
        validate_tag_state(state, entity_id)
        if parent_id is not None:
            validate_tag_state(state, parent_id)
        return entity_id, build_tag_update(
            entity_id,
            title=title,
            parent_id=UNSET if parent_id is None else parent_id,
            clear_parent=clear_parent,
        )

    def _simple_task_write(
        self,
        state: dict[str, dict[str, Any]],
        entity_id: str,
        builder: Callable[[str], dict[str, Any]],
    ) -> tuple[str | None, dict[str, Any]]:
        validate_task_state(state, entity_id)
        return entity_id, builder(entity_id)

    def _simple_project_write(
        self,
        state: dict[str, dict[str, Any]],
        entity_id: str,
        builder: Callable[[str], dict[str, Any]],
    ) -> tuple[str | None, dict[str, Any]]:
        validate_project_state(state, entity_id)
        return entity_id, builder(entity_id)

    def _simple_area_write(
        self,
        state: dict[str, dict[str, Any]],
        entity_id: str,
        builder: Callable[[str], dict[str, Any]],
    ) -> tuple[str | None, dict[str, Any]]:
        validate_area_state(state, entity_id)
        return entity_id, builder(entity_id)

    def _simple_tag_write(
        self,
        state: dict[str, dict[str, Any]],
        entity_id: str,
        builder: Callable[[str], dict[str, Any]],
    ) -> tuple[str | None, dict[str, Any]]:
        validate_tag_state(state, entity_id)
        return entity_id, builder(entity_id)

    def _commit_change_map(
        self,
        entity_id: str | None,
        change_map: dict[str, Any],
        *,
        dry_run: bool,
    ) -> dict[str, Any]:
        history = self.client.history()
        ancestor_index = int(history["latest-server-index"])
        schema = int(history.get("latest-schema-version") or 301)
        logger.info(
            "commit_prepare entity_id=%s dry_run=%s ancestor_index=%s schema=%s change=%s",
            entity_id,
            dry_run,
            ancestor_index,
            schema,
            _compact_json(_log_change_map(change_map)),
        )

        if dry_run:
            return {
                "entity_id": entity_id,
                "ancestor_index": ancestor_index,
                "schema": schema,
                "change_map": change_map,
                "dry_run": True,
            }

        try:
            commit = self.client.commit(change_map, ancestor_index, schema)
        except ThingsCloudError as exc:
            logger.exception(
                "commit_error entity_id=%s ancestor_index=%s schema=%s status=%s body=%s",
                entity_id,
                ancestor_index,
                schema,
                exc.status,
                _compact_json(_log_error_body(exc.body)),
            )
            if not _may_retry_commit(exc):
                raise
            history = self.client.history()
            ancestor_index = int(history["latest-server-index"])
            schema = int(history.get("latest-schema-version") or schema)
            logger.info(
                "commit_retry entity_id=%s ancestor_index=%s schema=%s change=%s",
                entity_id,
                ancestor_index,
                schema,
                _compact_json(_log_change_map(change_map)),
            )
            commit = self.client.commit(change_map, ancestor_index, schema)

        verify = self.client.history_items(ancestor_index)
        logger.info(
            "commit_success entity_id=%s ancestor_index=%s schema=%s verify_current_item_index=%s verify_items_count=%s commit=%s",
            entity_id,
            ancestor_index,
            schema,
            verify.get("current-item-index"),
            len(verify.get("items") or []),
            _compact_json(commit),
        )
        result = {
            "entity_id": entity_id,
            "ancestor_index": ancestor_index,
            "schema": schema,
            "commit": commit,
            "verify": {
                "current_item_index": verify.get("current-item-index"),
                "items_count": len(verify.get("items") or []),
            },
            "dry_run": False,
        }
        if self.store is not None:
            try:
                self.sync_entities(force=True)
            except ThingsCloudError as exc:
                logger.exception("post_commit_sync_error entity_id=%s status=%s", entity_id, exc.status)
                result["post_sync_error"] = str(exc)
        return result

    def _fresh_state(self) -> dict[str, dict[str, Any]]:
        self.sync_entities(force=True)
        return self._store().load_state()

    def _read(self, query: Callable[[dict[str, dict[str, Any]]], Any]) -> ReadResult:
        store = self._store()
        try:
            self.sync_entities()
            return ReadResult(query(store.load_state()))
        except ThingsCloudError as exc:
            if not store.has_entities():
                raise
            return ReadResult(query(store.load_state()), stale=True, sync_error=str(exc))

    def _read_todos(
        self,
        store_query: Callable[[EntityStore], Any],
        state_query: Callable[[dict[str, dict[str, Any]]], Any],
    ) -> ReadResult:
        store = self._store()
        try:
            self.sync_entities()
            return ReadResult(store_query(store))
        except ThingsCloudError as exc:
            if not store.has_entities():
                raise
            return ReadResult(state_query(store.load_state()), stale=True, sync_error=str(exc))

    def _store(self) -> EntityStore:
        if self.store is None:
            self.store = EntityStore.from_env()
        return self.store

    def _timezone(self) -> str:
        config = getattr(self.client, "config", None)
        return getattr(config, "timezone", "UTC")

    @staticmethod
    def _resolve_clearable(name: str, value: str | None, clear: bool) -> str | None | object:
        if clear and value is not None:
            raise ValueError(f"Use either clear_{name} or {name}, not both.")
        if clear:
            return None
        if value is None:
            return UNSET
        return value

    @staticmethod
    def _resolve_clearable_list(name: str, values: list[str] | None, clear: bool) -> list[str] | object:
        if clear and values is not None:
            raise ValueError(f"Use either clear_{name} or {name}, not both.")
        if clear:
            return []
        if values is None:
            return UNSET
        return list(values)


def _may_retry_commit(exc: ThingsCloudError) -> bool:
    if exc.status in {400, 409, 412}:
        return True
    body = exc.body
    if isinstance(body, str):
        return "ancestor" in body.casefold() or "index" in body.casefold()
    if isinstance(body, dict):
        text = " ".join(str(value) for value in body.values()).casefold()
        return "ancestor" in text or "index" in text
    return False


def validate_limit(limit: int) -> int:
    if isinstance(limit, bool):
        raise ValueError(f"limit must be an integer from 0 to {MAX_LIMIT}.")
    try:
        parsed = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"limit must be an integer from 0 to {MAX_LIMIT}.") from exc
    if not 0 <= parsed <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer from 0 to {MAX_LIMIT}.")
    return parsed


def validate_status(status: str, allowed: set[str], name: str) -> str:
    if status not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"Invalid {name}: {status}. Choose from {choices}.")
    return status


def validate_query(query: str) -> str:
    text = query.strip()
    if not text:
        raise ValueError("query must be non-empty.")
    return text


def should_sync(store: EntityStore) -> bool:
    ttl = sync_ttl_seconds()
    if ttl <= 0:
        return True
    latest_index = store.latest_item_index()
    last_synced_at = store.last_synced_at()
    if latest_index is None or last_synced_at is None or not store.has_entities():
        return True
    return (time.time() - last_synced_at) >= ttl


def sync_ttl_seconds() -> float:
    value = os.environ.get("THINGS_MCP_SYNC_TTL_SECONDS", "0").strip() or "0"
    try:
        ttl = float(value)
    except ValueError as exc:
        raise ValueError("THINGS_MCP_SYNC_TTL_SECONDS must be a non-negative number.") from exc
    if ttl < 0:
        raise ValueError("THINGS_MCP_SYNC_TTL_SECONDS must be a non-negative number.")
    return ttl


def log_payloads_enabled() -> bool:
    return os.environ.get("THINGS_MCP_LOG_PAYLOADS", "").strip().lower() in {"1", "true", "yes", "on"}


def _log_change_map(change_map: dict[str, Any]) -> dict[str, Any]:
    if log_payloads_enabled():
        return change_map
    return {
        "redacted": True,
        "entity_count": len(change_map),
        "entity_ids": list(change_map.keys()),
    }


def _log_error_body(body: Any) -> Any:
    if log_payloads_enabled():
        return body
    if body is None:
        return None
    return {"redacted": True, "type": type(body).__name__}


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _parse_local_date_end(value: str | None, timezone_name: str) -> int | None:
    start = parse_local_date(value, timezone_name)
    if start is None:
        return None
    return start + 86_399


def _parse_things_date_start(value: str | None, timezone_name: str) -> int | None:
    parsed = _resolve_query_date(value, timezone_name)
    if parsed is None:
        return None
    return min(_local_midnight_epoch(parsed, timezone_name), _utc_midnight_epoch(parsed))


def _parse_things_date_end(value: str | None, timezone_name: str) -> int | None:
    parsed = _resolve_query_date(value, timezone_name)
    if parsed is None:
        return None
    return max(_local_midnight_epoch(parsed, timezone_name), _utc_midnight_epoch(parsed)) + 86_399


def _resolve_query_date(value: str | None, timezone_name: str) -> date | None:
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


def _local_midnight_epoch(parsed: date, timezone_name: str) -> int:
    tz = ZoneInfo(timezone_name)
    return int(datetime(parsed.year, parsed.month, parsed.day, tzinfo=tz).timestamp())


def _utc_midnight_epoch(parsed: date) -> int:
    return int(datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc).timestamp())
