from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import time
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .cloud_client import ConfigError, ThingsCloudError
from .service import ReadResult, ThingsService


logger = logging.getLogger("things_mcp.server")


def csv_env(name: str, default: str) -> list[str]:
    return [value.strip() for value in os.environ.get(name, default).split(",") if value.strip()]


mcp = FastMCP(
    "Things Cloud",
    host="0.0.0.0",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=csv_env("THINGS_MCP_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*,[::1]:*"),
        allowed_origins=csv_env("THINGS_MCP_ALLOWED_ORIGINS", ""),
    ),
)


def ok(data: Any) -> dict[str, Any]:
    if isinstance(data, ReadResult):
        response = {"ok": True, "data": data.data, "error": None}
        if data.stale:
            response["stale"] = True
            response["sync_error"] = data.sync_error
        return response
    return {"ok": True, "data": data, "error": None}


def fail(code: str, message: str, *, status: int | None = None) -> dict[str, Any]:
    return {"ok": False, "data": None, "error": {"code": code, "message": message, "status": status}}


def service() -> ThingsService:
    return ThingsService.from_env()


def guard(call) -> dict[str, Any]:
    try:
        response = ok(call())
        logger.info("tool_response %s", _compact_json(_summarize_response(response)))
        return response
    except ConfigError as exc:
        logger.exception("tool_configuration_error")
        return fail("configuration_error", str(exc))
    except ThingsCloudError as exc:
        logger.exception("tool_things_cloud_error status=%s body=%s", exc.status, _compact_json(_log_body(exc.body)))
        return fail("things_cloud_error", str(exc), status=exc.status)
    except ValueError as exc:
        logger.exception("tool_validation_error")
        return fail("validation_error", str(exc))


@mcp.tool()
def list_todos(
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
) -> dict[str, Any]:
    """List Things to-dos from Things Cloud."""
    return guard(
        lambda: service().list_todos(
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
    )


@mcp.tool()
def list_today_todos(
    project_id: str | None = None,
    area_id: str | None = None,
    tag_ids: list[str] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List open to-dos that should appear in a Things Today-style view."""
    return guard(
        lambda: service().list_todos(
            status="open",
            project_id=project_id,
            area_id=area_id,
            tag_ids=tag_ids,
            start_to="today",
            limit=limit,
        )
    )


@mcp.tool()
def list_inbox_todos(tag_ids: list[str] | None = None, limit: int = 100) -> dict[str, Any]:
    """List open to-dos in the Things Inbox."""
    return guard(lambda: service().list_inbox_todos(tag_ids=tag_ids, limit=limit))


@mcp.tool()
def list_upcoming_todos(
    start_from: str | None = "tomorrow",
    start_to: str | None = None,
    tag_ids: list[str] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List open scheduled to-dos after today by default."""
    return guard(
        lambda: service().list_upcoming_todos(
            start_from=start_from,
            start_to=start_to,
            tag_ids=tag_ids,
            limit=limit,
        )
    )


@mcp.tool()
def list_deadline_todos(
    deadline_from: str | None = None,
    deadline_to: str | None = None,
    tag_ids: list[str] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List open to-dos that have a deadline."""
    return guard(
        lambda: service().list_deadline_todos(
            deadline_from=deadline_from,
            deadline_to=deadline_to,
            tag_ids=tag_ids,
            limit=limit,
        )
    )


@mcp.tool()
def list_logbook_todos(limit: int = 100) -> dict[str, Any]:
    """List completed or canceled to-dos."""
    return guard(lambda: service().list_logbook_todos(limit=limit))


@mcp.tool()
def search_todos(
    query: str,
    status: str = "all",
    created_from: str | None = None,
    created_to: str | None = None,
    deadline_from: str | None = None,
    deadline_to: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Search Things to-dos by title and note text."""
    return guard(
        lambda: service().search_todos(
            query=query,
            status=status,
            created_from=created_from,
            created_to=created_to,
            deadline_from=deadline_from,
            deadline_to=deadline_to,
            limit=limit,
        )
    )


@mcp.tool()
def search_projects(query: str, status: str = "all", limit: int = 100) -> dict[str, Any]:
    """Search Things projects by title and note text."""
    return guard(lambda: service().search_projects(query=query, status=status, limit=limit))


@mcp.tool()
def search_tags(query: str, status: str = "all", limit: int = 100) -> dict[str, Any]:
    """Search Things tags by title."""
    return guard(lambda: service().search_tags(query=query, status=status, limit=limit))


@mcp.tool()
def get_item(entity_id: str) -> dict[str, Any]:
    """Get one folded Things entity by id."""
    return guard(lambda: service().get_item(entity_id=entity_id))


@mcp.tool()
def create_todo(
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
    """Create a Things to-do."""
    return guard(
        lambda: service().create_todo(
            title=title,
            notes=notes,
            when=when,
            reminder_time=reminder_time,
            deadline=deadline,
            tag_ids=tag_ids,
            checklist_items=checklist_items,
            project_id=project_id,
            area_id=area_id,
            list_name=list_name,
            dry_run=dry_run,
        )
    )


@mcp.tool()
def update_todo(
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
    """Update selected fields on an existing Things to-do."""
    return guard(
        lambda: service().update_todo(
            entity_id=entity_id,
            title=title,
            notes=notes,
            clear_notes=clear_notes,
            when=when,
            clear_when=clear_when,
            reminder_time=reminder_time,
            clear_reminder=clear_reminder,
            deadline=deadline,
            clear_deadline=clear_deadline,
            tag_ids=tag_ids,
            clear_tags=clear_tags,
            project_id=project_id,
            area_id=area_id,
            list_name=list_name,
            dry_run=dry_run,
        )
    )


@mcp.tool()
def complete_todo(entity_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Mark a Things to-do as completed."""
    return guard(lambda: service().complete_todo(entity_id=entity_id, dry_run=dry_run))


@mcp.tool()
def cancel_todo(entity_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Mark a Things to-do as canceled."""
    return guard(lambda: service().cancel_todo(entity_id=entity_id, dry_run=dry_run))


@mcp.tool()
def delete_todo(entity_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Move a Things to-do to Trash."""
    return guard(lambda: service().delete_todo(entity_id=entity_id, dry_run=dry_run))


@mcp.tool()
def list_projects(
    status: str = "open",
    created_from: str | None = None,
    created_to: str | None = None,
    deadline_from: str | None = None,
    deadline_to: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List Things projects."""
    return guard(
        lambda: service().list_projects(
            status=status,
            created_from=created_from,
            created_to=created_to,
            deadline_from=deadline_from,
            deadline_to=deadline_to,
            limit=limit,
        )
    )


@mcp.tool()
def create_project(
    title: str,
    notes: str = "",
    when: str | None = None,
    deadline: str | None = None,
    area_ids: list[str] | None = None,
    tag_ids: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create a Things project."""
    return guard(
        lambda: service().create_project(
            title=title,
            notes=notes,
            when=when,
            deadline=deadline,
            area_ids=area_ids,
            tag_ids=tag_ids,
            dry_run=dry_run,
        )
    )


@mcp.tool()
def update_project(
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
    """Update selected fields on a Things project."""
    return guard(
        lambda: service().update_project(
            entity_id=entity_id,
            title=title,
            notes=notes,
            clear_notes=clear_notes,
            when=when,
            clear_when=clear_when,
            deadline=deadline,
            clear_deadline=clear_deadline,
            area_ids=area_ids,
            clear_area=clear_area,
            tag_ids=tag_ids,
            clear_tags=clear_tags,
            dry_run=dry_run,
        )
    )


@mcp.tool()
def complete_project(entity_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Mark a Things project completed and archive unfinished child tasks."""
    return guard(lambda: service().complete_project(entity_id=entity_id, dry_run=dry_run))


@mcp.tool()
def cancel_project(entity_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Mark a Things project canceled and cancel unfinished child tasks."""
    return guard(lambda: service().cancel_project(entity_id=entity_id, dry_run=dry_run))


@mcp.tool()
def delete_project(entity_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Move a Things project to Trash."""
    return guard(lambda: service().delete_project(entity_id=entity_id, dry_run=dry_run))


@mcp.tool()
def list_headings(project_id: str | None = None, limit: int = 100) -> dict[str, Any]:
    """List active headings, optionally filtered by project."""
    return guard(lambda: service().list_headings(project_id=project_id, limit=limit))


@mcp.tool()
def create_heading(title: str, project_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Create a heading inside a project."""
    return guard(lambda: service().create_heading(title=title, project_id=project_id, dry_run=dry_run))


@mcp.tool()
def update_heading(
    entity_id: str,
    title: str | None = None,
    notes: str | None = None,
    clear_notes: bool = False,
    project_id: str | None = None,
    tag_ids: list[str] | None = None,
    clear_tags: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Update a heading."""
    return guard(
        lambda: service().update_heading(
            entity_id=entity_id,
            title=title,
            notes=notes,
            clear_notes=clear_notes,
            project_id=project_id,
            tag_ids=tag_ids,
            clear_tags=clear_tags,
            dry_run=dry_run,
        )
    )


@mcp.tool()
def list_areas(
    status: str = "open",
    created_from: str | None = None,
    created_to: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List Things areas."""
    return guard(
        lambda: service().list_areas(
            status=status,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
        )
    )


@mcp.tool()
def create_area(title: str, tag_ids: list[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Create an area."""
    return guard(lambda: service().create_area(title=title, tag_ids=tag_ids, dry_run=dry_run))


@mcp.tool()
def update_area(
    entity_id: str,
    title: str | None = None,
    tag_ids: list[str] | None = None,
    clear_tags: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Update an area."""
    return guard(
        lambda: service().update_area(
            entity_id=entity_id,
            title=title,
            tag_ids=tag_ids,
            clear_tags=clear_tags,
            dry_run=dry_run,
        )
    )


@mcp.tool()
def delete_area(entity_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Delete an area."""
    return guard(lambda: service().delete_area(entity_id=entity_id, dry_run=dry_run))


@mcp.tool()
def list_tags(
    status: str = "open",
    created_from: str | None = None,
    created_to: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List Things tags."""
    return guard(
        lambda: service().list_tags(
            status=status,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
        )
    )


@mcp.tool()
def create_tag(title: str, parent_id: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Create a tag."""
    return guard(lambda: service().create_tag(title=title, parent_id=parent_id, dry_run=dry_run))


@mcp.tool()
def update_tag(
    entity_id: str,
    title: str | None = None,
    parent_id: str | None = None,
    clear_parent: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Update a tag."""
    return guard(
        lambda: service().update_tag(
            entity_id=entity_id,
            title=title,
            parent_id=parent_id,
            clear_parent=clear_parent,
            dry_run=dry_run,
        )
    )


@mcp.tool()
def delete_tag(entity_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Delete a tag."""
    return guard(lambda: service().delete_tag(entity_id=entity_id, dry_run=dry_run))


async def healthz(_: Request) -> Response:
    return JSONResponse({"ok": True})


class BearerTokenMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        token = os.environ.get("THINGS_MCP_AUTH_TOKEN")
        if scope["type"] != "http" or scope.get("path") == "/healthz":
            await self.app(scope, receive, send)
            return
        if not token:
            if _allow_unauthenticated_enabled():
                await self.app(scope, receive, send)
                return
            response = JSONResponse(
                {
                    "ok": False,
                    "error": "THINGS_MCP_AUTH_TOKEN is required unless THINGS_MCP_ALLOW_UNAUTHENTICATED=true.",
                },
                status_code=503,
            )
            await response(scope, receive, send)
            return
        headers = {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in scope.get("headers", [])
        }
        if headers.get("authorization") != f"Bearer {token}":
            response = JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.monotonic()
        body = b""
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                break
            body += message.get("body", b"")
            more_body = message.get("more_body", False)

        status_code: int | None = None

        body_sent = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal body_sent
            if body_sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def logging_send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        client = scope.get("client")
        request_log = {
            "method": scope.get("method"),
            "path": scope.get("path"),
            "query_string": (scope.get("query_string") or b"").decode("latin1"),
            "client": client[0] if client else None,
            "body": _log_http_body(body),
        }
        logger.info("http_request %s", _compact_json(request_log))
        try:
            await self.app(scope, replay_receive, logging_send)
        finally:
            response_log = {
                "method": scope.get("method"),
                "path": scope.get("path"),
                "status": status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            }
            logger.info("http_response %s", _compact_json(response_log))


def _decode_body(body: bytes) -> Any:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _log_http_body(body: bytes) -> Any:
    if not body:
        return None
    if _log_payloads_enabled():
        return _decode_body(body)
    return {"redacted": True, "bytes": len(body)}


def _log_body(value: Any) -> Any:
    if _log_payloads_enabled():
        return value
    if value is None:
        return None
    return {"redacted": True, "type": type(value).__name__}


def _log_payloads_enabled() -> bool:
    return os.environ.get("THINGS_MCP_LOG_PAYLOADS", "").strip().lower() in {"1", "true", "yes", "on"}


def _allow_unauthenticated_enabled() -> bool:
    return os.environ.get("THINGS_MCP_ALLOW_UNAUTHENTICATED", "").strip().lower() in {"1", "true", "yes", "on"}


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _summarize_response(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if isinstance(data, list):
        data_summary: Any = {"type": "list", "count": len(data)}
    elif isinstance(data, dict):
        data_summary = {
            key: data.get(key)
            for key in ["entity_id", "ancestor_index", "schema", "dry_run", "post_sync_error"]
            if key in data
        }
        if "verify" in data:
            data_summary["verify"] = data["verify"]
    else:
        data_summary = data
    return {
        "ok": response.get("ok"),
        "data": data_summary,
        "error": response.get("error"),
        "stale": response.get("stale"),
        "sync_error": response.get("sync_error"),
    }


@contextlib.asynccontextmanager
async def lifespan(_: Starlette):
    async with mcp.session_manager.run():
        yield


def configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("THINGS_MCP_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


app = BearerTokenMiddleware(
    RequestLoggingMiddleware(
        Starlette(
            routes=[
                Route("/healthz", healthz, methods=["GET"]),
                Mount("/", app=mcp.streamable_http_app()),
            ],
            lifespan=lifespan,
        )
    )
)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Run the Things Cloud MCP server.")
    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.command not in {None, "serve"}:
        parser.error(f"Unsupported command: {args.command}")
    uvicorn.run("things_mcp.server:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
