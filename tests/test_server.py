from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from things_mcp import server


class StubService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_todo(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_todo", kwargs))
        return {"entity_id": "task", "dry_run": kwargs["dry_run"]}

    def update_project(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("update_project", kwargs))
        return {"entity_id": kwargs["entity_id"], "dry_run": kwargs["dry_run"]}

    def list_headings(self, **kwargs: Any) -> server.ReadResult:
        self.calls.append(("list_headings", kwargs))
        return server.ReadResult([{"id": "heading"}])

    def list_inbox_todos(self, **kwargs: Any) -> server.ReadResult:
        self.calls.append(("list_inbox_todos", kwargs))
        return server.ReadResult([{"id": "inbox"}])

    def list_upcoming_todos(self, **kwargs: Any) -> server.ReadResult:
        self.calls.append(("list_upcoming_todos", kwargs))
        return server.ReadResult([{"id": "upcoming"}])

    def list_deadline_todos(self, **kwargs: Any) -> server.ReadResult:
        self.calls.append(("list_deadline_todos", kwargs))
        return server.ReadResult([{"id": "deadline"}])

    def list_logbook_todos(self, **kwargs: Any) -> server.ReadResult:
        self.calls.append(("list_logbook_todos", kwargs))
        return server.ReadResult([{"id": "logbook"}])

    def search_projects(self, **kwargs: Any) -> server.ReadResult:
        self.calls.append(("search_projects", kwargs))
        return server.ReadResult([{"id": "project"}])

    def search_tags(self, **kwargs: Any) -> server.ReadResult:
        self.calls.append(("search_tags", kwargs))
        return server.ReadResult([{"id": "tag"}])


def test_create_todo_tool_forwards_new_arguments(monkeypatch) -> None:
    stub = StubService()
    monkeypatch.setattr(server, "service", lambda: stub)

    result = server.create_todo(
        title="Task",
        reminder_time="09:00",
        project_id="project",
        area_id=None,
        list_name=None,
        dry_run=True,
    )

    assert result == {"ok": True, "data": {"entity_id": "task", "dry_run": True}, "error": None}
    assert stub.calls == [
        (
            "create_todo",
            {
                "title": "Task",
                "notes": "",
                "when": None,
                "reminder_time": "09:00",
                "deadline": None,
                "tag_ids": None,
                "checklist_items": None,
                "project_id": "project",
                "area_id": None,
                "list_name": None,
                "dry_run": True,
            },
        )
    ]


def test_update_project_tool_forwards_clear_arguments(monkeypatch) -> None:
    stub = StubService()
    monkeypatch.setattr(server, "service", lambda: stub)

    result = server.update_project(entity_id="project", clear_area=True, clear_tags=True, dry_run=True)

    assert result["ok"] is True
    assert stub.calls[0][0] == "update_project"
    assert stub.calls[0][1]["clear_area"] is True
    assert stub.calls[0][1]["clear_tags"] is True


def test_list_headings_tool_wraps_read_result(monkeypatch) -> None:
    stub = StubService()
    monkeypatch.setattr(server, "service", lambda: stub)

    result = server.list_headings(project_id="project")

    assert result == {"ok": True, "data": [{"id": "heading"}], "error": None}
    assert stub.calls == [("list_headings", {"project_id": "project", "limit": 100})]


def test_convenience_tools_forward_arguments(monkeypatch) -> None:
    stub = StubService()
    monkeypatch.setattr(server, "service", lambda: stub)

    assert server.list_inbox_todos(tag_ids=["tag"])["data"] == [{"id": "inbox"}]
    assert server.list_upcoming_todos(start_from="tomorrow", start_to="2026-05-01")["data"] == [{"id": "upcoming"}]
    assert server.list_deadline_todos(deadline_to="today")["data"] == [{"id": "deadline"}]
    assert server.list_logbook_todos()["data"] == [{"id": "logbook"}]
    assert server.search_projects(query="alpha")["data"] == [{"id": "project"}]
    assert server.search_tags(query="focus")["data"] == [{"id": "tag"}]

    assert stub.calls == [
        ("list_inbox_todos", {"tag_ids": ["tag"], "limit": 100}),
        ("list_upcoming_todos", {"start_from": "tomorrow", "start_to": "2026-05-01", "tag_ids": None, "limit": 100}),
        ("list_deadline_todos", {"deadline_from": None, "deadline_to": "today", "tag_ids": None, "limit": 100}),
        ("list_logbook_todos", {"limit": 100}),
        ("search_projects", {"query": "alpha", "status": "all", "limit": 100}),
        ("search_tags", {"query": "focus", "status": "all", "limit": 100}),
    ]


def test_guard_converts_value_error_to_validation_error() -> None:
    result = server.guard(lambda: (_ for _ in ()).throw(ValueError("bad input")))

    assert result == {
        "ok": False,
        "data": None,
        "error": {"code": "validation_error", "message": "bad input", "status": None},
    }


def test_healthz_does_not_expose_configuration_state() -> None:
    with TestClient(server.app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_request_log_body_redacts_by_default(monkeypatch) -> None:
    monkeypatch.delenv("THINGS_MCP_LOG_PAYLOADS", raising=False)

    body = server._log_http_body(b'{"title":"Secret"}')

    assert body == {"redacted": True, "bytes": 18}


def test_request_log_body_can_include_payload(monkeypatch) -> None:
    monkeypatch.setenv("THINGS_MCP_LOG_PAYLOADS", "true")

    body = server._log_http_body(b'{"title":"Secret"}')

    assert body == {"title": "Secret"}


def test_unauthorized_requests_do_not_enter_request_logger(monkeypatch) -> None:
    log_calls = []
    monkeypatch.setenv("THINGS_MCP_AUTH_TOKEN", "secret")
    monkeypatch.setattr(server.logger, "info", lambda *args, **kwargs: log_calls.append((args, kwargs)))

    async def inner_app(scope, receive, send) -> None:
        response = server.JSONResponse({"ok": True})
        await response(scope, receive, send)

    app = server.BearerTokenMiddleware(server.RequestLoggingMiddleware(inner_app))

    assert isinstance(server.app, server.BearerTokenMiddleware)
    assert isinstance(server.app.app, server.RequestLoggingMiddleware)

    response = TestClient(app).post("/mcp", content=b"x" * 1024)

    assert response.status_code == 401
    assert log_calls == []


def test_missing_auth_token_rejects_mcp_requests_by_default(monkeypatch) -> None:
    monkeypatch.delenv("THINGS_MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("THINGS_MCP_ALLOW_UNAUTHENTICATED", raising=False)
    entered = False

    async def inner_app(scope, receive, send) -> None:
        nonlocal entered
        entered = True
        response = server.JSONResponse({"ok": True})
        await response(scope, receive, send)

    app = server.BearerTokenMiddleware(inner_app)
    response = TestClient(app).post("/mcp")

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "error": "THINGS_MCP_AUTH_TOKEN is required unless THINGS_MCP_ALLOW_UNAUTHENTICATED=true.",
    }
    assert entered is False


def test_allow_unauthenticated_opt_in_allows_missing_auth_token(monkeypatch) -> None:
    monkeypatch.delenv("THINGS_MCP_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("THINGS_MCP_ALLOW_UNAUTHENTICATED", "true")

    async def inner_app(scope, receive, send) -> None:
        response = server.JSONResponse({"ok": True})
        await response(scope, receive, send)

    app = server.BearerTokenMiddleware(inner_app)
    response = TestClient(app).post("/mcp")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_readme_documents_public_tools() -> None:
    readme = Path("README.md").read_text()

    for tool_name in [
        "list_inbox_todos",
        "list_upcoming_todos",
        "list_deadline_todos",
        "list_logbook_todos",
        "search_projects",
        "search_tags",
        "cancel_todo",
        "create_heading",
    ]:
        assert f"`{tool_name}`" in readme
