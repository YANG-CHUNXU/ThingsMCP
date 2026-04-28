# ThingsMCP

[English](README.md) | [简体中文](README.zh-CN.md)

Personal, unofficial MCP server for Things Cloud. It talks to Things Cloud
directly and avoids macOS-only dependencies, so it can run on a headless
server or any supported Python environment.

## Important Notice

This project is unofficial, unsupported by Cultured Code, and intended for
personal use only. It relies on Things Cloud behavior that is not documented as
a public API and may change or stop working at any time.

Using non-public Things Cloud endpoints may violate Cultured Code's service
terms. Use this software at your own risk. Keep credentials private, bind the
server to trusted interfaces only, and test write operations with `dry_run`
first. This project is not a stable SDK and should not be used to provide a
hosted or shared Things Cloud service.

Write operations have not been exhaustively verified against Things Cloud.
Incorrect write payloads may sync invalid data to Things Cloud and could cause
the official Things app to behave incorrectly or crash. Back up your Things data
before enabling writes.

## Configuration

Copy `.env.example` to `.env` and fill in:

```bash
THINGS_CLOUD_EMAIL=you@example.com
THINGS_CLOUD_PASSWORD=your-things-cloud-password
THINGS_CLOUD_HISTORY_KEY=your-history-key
THINGS_MCP_AUTH_TOKEN=long-random-token
THINGS_MCP_ALLOW_UNAUTHENTICATED=false
THINGS_TIMEZONE=Etc/UTC
THINGS_MCP_DB_PATH=~/.cache/things-mcp/entities.sqlite
THINGS_MCP_LOG_PAYLOADS=false
THINGS_MCP_SYNC_TTL_SECONDS=0
```

The `history_key` is part of the Things Cloud account metadata and must be
provided through configuration together with the account credentials. On a Mac
where Things is installed and synced, you can usually detect it from the local
Things database:

```bash
python scripts/detect_history_key.py --show-metadata
```

Set `THINGS_TIMEZONE` to the IANA time zone you use with Things, for example
`America/New_York`, `Europe/Berlin`, or `Asia/Shanghai`. If it is omitted,
ThingsMCP uses `UTC`.

Read tools keep a local SQLite cache of folded Things entities. By default it
is stored at `~/.cache/things-mcp/entities.sqlite`; set `THINGS_MCP_DB_PATH` to
override the location. Each read tool syncs from Things Cloud before querying
the cache. `THINGS_MCP_SYNC_TTL_SECONDS` can skip repeated read syncs for a
short period; the default `0` keeps the safest behavior and syncs before every
read. If sync fails after a cache exists, the response includes `stale: true`
and `sync_error`.

Request bodies and Things write payloads are redacted from logs by default. Set
`THINGS_MCP_LOG_PAYLOADS=true` only while debugging locally if full payload logs
are needed.

## Run

```bash
python -m pip install -e ".[test]"
things-mcp serve --host 127.0.0.1 --port 8765
```

The MCP endpoint is `http://127.0.0.1:8765/mcp`. Health checks are available at
`http://127.0.0.1:8765/healthz`.

The default host is local-only. Do not expose this server directly to the
public internet.

By default, `THINGS_MCP_AUTH_TOKEN` is required. MCP requests must include:

```http
Authorization: Bearer <token>
```

For local experiments only, you can set `THINGS_MCP_ALLOW_UNAUTHENTICATED=true`
to run without a bearer token. Do not use that mode on a network-reachable
server.

## Docker

```bash
docker compose up --build
```

The default compose file binds to `127.0.0.1:8765`, runs as a non-root user,
and stores the SQLite cache in a named Docker volume.

The Docker image refuses to start unless `THINGS_MCP_AUTH_TOKEN` is set or
`THINGS_MCP_ALLOW_UNAUTHENTICATED=true` is explicitly configured.

## Tools

All tool responses use this shape:

```json
{"ok": true, "data": "...", "error": null}
```

Failures use `ok: false` with an `error.code` and `error.message`. Read tools
sync from Things Cloud before querying the local cache. If sync fails after a
cache exists, the response includes `stale: true` and `sync_error`, and `data`
comes from the local cache.

Date arguments accept `YYYY-MM-DD`, `today`, or `tomorrow`. Dates are
interpreted in `THINGS_TIMEZONE`, or `UTC` when `THINGS_TIMEZONE` is not set. Range
filters are inclusive: `*_from` is the lower bound, `*_to` is the upper bound,
and using the same date for both returns items on that one date. Items without
the selected date field are excluded when that date field is filtered.

`limit` defaults to `100` and must be between `0` and `500`.

For Things Today-style to-do results, use `list_today_todos` or call
`list_todos` with `status: "open"` and `start_to: "today"`. An exact range such
as `start_from: "today"` plus `start_to: "today"` only matches items whose
stored `When` date is today, and it will miss unfinished items scheduled on
previous days that Things still shows in Today.

Status values used by to-do and project tools:

- `open`: not deleted, not trashed, not completed, and not canceled.
- `archived`: completed or canceled, but not deleted or trashed.
- `completed`: completed/logged only.
- `trashed`: in Trash, but not permanently deleted.
- `deleted`: deleted from the folded Things history.
- `all`: every non-deleted item, including trashed and archived items.

Area and tag tools support `open`, `trashed`, `deleted`, and `all`.

### `list_todos`

Lists Things to-dos. Supported arguments:

- `status`: one of the status values above. Defaults to `open`.
- `project_id`: only include to-dos attached to this Things project id.
- `area_id`: only include to-dos attached to this Things area id.
- `tag_ids`: only include to-dos that have all listed Things tag ids.
- `created_from` / `created_to`: filter by creation date.
- `start_from` / `start_to`: filter by Things `When` / scheduled date.
- `deadline_from` / `deadline_to`: filter by deadline.
- `limit`: maximum number of returned rows. Defaults to `100`.

Results are ordered by modified time descending.

Example: Things Today-style to-dos, including unfinished items scheduled before
today:

```json
{
  "status": "open",
  "start_to": "today"
}
```

Example: to-dos whose stored `When` date is exactly today:

```json
{
  "status": "open",
  "start_from": "today",
  "start_to": "today"
}
```

Example: to-dos due on or before today:

```json
{
  "status": "open",
  "deadline_to": "today"
}
```

### `list_today_todos`

Lists open to-dos that should appear in a Things Today-style view. It returns
to-dos whose Things `When` / scheduled date is today or earlier, so unfinished
items scheduled on previous days are included. To-dos without a Things `When` /
scheduled date are not included.

Supported arguments:

- `project_id`: only include to-dos attached to this Things project id.
- `area_id`: only include to-dos attached to this Things area id.
- `tag_ids`: only include to-dos that have all listed Things tag ids.
- `limit`: maximum number of returned rows. Defaults to `100`.

Equivalent `list_todos` call:

```json
{
  "status": "open",
  "start_to": "today"
}
```

### `list_inbox_todos`

Lists open to-dos in the Things Inbox. Supported arguments:

- `tag_ids`: only include to-dos that have all listed Things tag ids.
- `limit`: maximum number of returned rows. Defaults to `100`.

### `list_upcoming_todos`

Lists open scheduled to-dos after today by default. Supported arguments:

- `start_from`: lower scheduled-date bound. Defaults to `tomorrow`.
- `start_to`: upper scheduled-date bound.
- `tag_ids`: only include to-dos that have all listed Things tag ids.
- `limit`: maximum number of returned rows. Defaults to `100`.

### `list_deadline_todos`

Lists open to-dos that have a deadline. Supported arguments:

- `deadline_from` / `deadline_to`: filter by deadline.
- `tag_ids`: only include to-dos that have all listed Things tag ids.
- `limit`: maximum number of returned rows. Defaults to `100`.

### `list_logbook_todos`

Lists completed or canceled to-dos. Supported arguments:

- `limit`: maximum number of returned rows. Defaults to `100`.

### `search_todos`

Searches Things to-dos by title and plain note text. The query is
case-insensitive and must be non-empty after trimming. Supported arguments:

- `query`: text to search for.
- `status`: one of the to-do status values above. Defaults to `all`.
- `created_from` / `created_to`: filter by creation date.
- `deadline_from` / `deadline_to`: filter by deadline.
- `limit`: maximum number of returned rows. Defaults to `100`.

This tool does not support `start_from` / `start_to`; use `list_todos` to query
by Things `When` / scheduled date.

### `search_projects`

Searches Things projects by title and plain note text. Supported arguments:

- `query`: text to search for. Must be non-empty after trimming.
- `status`: one of the to-do/project status values above. Defaults to `all`.
- `limit`: maximum number of returned rows. Defaults to `100`.

### `search_tags`

Searches Things tags by title. Supported arguments:

- `query`: text to search for. Must be non-empty after trimming.
- `status`: `open`, `trashed`, `deleted`, or `all`. Defaults to `all`.
- `limit`: maximum number of returned rows. Defaults to `100`.

### `get_item`

Returns one folded Things entity by `entity_id`. The id can refer to a to-do,
project, area, tag, or another synced Things entity. Returns `null` data when
the id is not present in the folded state.

### `create_todo`

Creates a Things to-do in the Inbox. Supported arguments:

- `title`: required to-do title.
- `notes`: note text; Markdown-style markup supported by Things notes is
  accepted.
- `when`: Things `When` / scheduled date.
- `reminder_time`: reminder time on the scheduled date, as `HH:MM` in
  5-minute increments. Requires `when` or `list_name: "today"`.
- `deadline`: deadline date.
- `tag_ids`: Things tag entity ids. Duplicate ids are removed while preserving
  order.
- `checklist_items`: checklist item titles to attach to the new to-do.
- `project_id`: create the to-do inside this Things project.
- `area_id`: create the to-do inside this Things area.
- `list_name`: create the to-do in a built-in list: `inbox`, `today`,
  `anytime`, `someday`, or `logbook`.
- `dry_run`: when `true`, returns the Things Cloud change payload without
  committing it.

### `update_todo`

Updates selected fields on an existing Things to-do. Supported arguments:

- `entity_id`: required Things to-do id.
- `title`: replaces the title when provided.
- `notes`: replaces the note text when provided; Markdown-style markup
  supported by Things notes is accepted.
- `when`: replaces the Things `When` / scheduled date when provided.
- `reminder_time`: replaces the reminder time on the to-do's scheduled date,
  as `HH:MM` in 5-minute increments. Use `clear_reminder: true` to remove it.
- `deadline`: replaces the deadline when provided.
- `tag_ids`: replaces the full tag id list when provided. Duplicate ids are
  removed while preserving order.
- `project_id`: moves the to-do into this Things project.
- `area_id`: moves the to-do into this Things area.
- `list_name`: moves the to-do to a built-in list: `inbox`, `today`,
  `anytime`, `someday`, or `logbook`.
- `clear_notes` / `clear_when` / `clear_reminder` / `clear_deadline` /
  `clear_tags`: clears the corresponding field.
- `dry_run`: when `true`, returns the Things Cloud change payload without
  committing it.

Only provided, non-null fields are changed. At least one mutable field must be
provided.

### `complete_todo`

Marks a Things to-do as completed so it enters the Things Logbook. Requires
`entity_id`. `dry_run: true` returns the Things Cloud change payload without
committing it.

### `cancel_todo`

Marks a Things to-do as canceled. Requires `entity_id`. `dry_run: true` returns
the Things Cloud change payload without committing it.

### `delete_todo`

Moves a Things to-do to Trash. This is a soft delete, not permanent deletion
from Things Cloud. Requires `entity_id`. `dry_run: true` returns the Things
Cloud change payload without committing it.

### `list_projects`

Lists Things projects by status, creation date, and deadline. Supported
arguments:

- `status`: one of the to-do/project status values above. Defaults to `open`.
- `created_from` / `created_to`: filter by creation date.
- `deadline_from` / `deadline_to`: filter by project deadline.
- `limit`: maximum number of returned rows. Defaults to `100`.

Results are ordered by title. Returned projects include `archived` and
`in_logbook` flags for projects that have entered the Things Logbook.

### `create_project`

Creates a Things project. Supported arguments:

- `title`: required project title.
- `notes`: project note text.
- `when`: Things `When` / scheduled date.
- `deadline`: project deadline date.
- `area_ids`: Things area entity ids. Duplicate ids are removed while
  preserving order.
- `tag_ids`: Things tag entity ids. Duplicate ids are removed while preserving
  order.
- `dry_run`: when `true`, returns the Things Cloud change payload without
  committing it.

### `update_project`

Updates selected fields on an existing Things project. Supported arguments:

- `entity_id`: required Things project id.
- `title`: replaces the title when provided.
- `notes`: replaces the note text when provided.
- `when`: replaces the Things `When` / scheduled date when provided.
- `deadline`: replaces the deadline when provided.
- `area_ids`: replaces the full area id list when provided.
- `tag_ids`: replaces the full tag id list when provided.
- `clear_notes` / `clear_when` / `clear_deadline` / `clear_area` /
  `clear_tags`: clears the corresponding field.
- `dry_run`: when `true`, returns the Things Cloud change payload without
  committing it.

### `complete_project`

Marks a Things project completed and archives unfinished child tasks/headings.
Requires `entity_id`. `dry_run: true` returns the Things Cloud change payload
without committing it.

### `cancel_project`

Marks a Things project canceled and cancels unfinished child tasks/headings.
Requires `entity_id`. `dry_run: true` returns the Things Cloud change payload
without committing it.

### `delete_project`

Moves a Things project to Trash. This is a soft delete, not permanent deletion
from Things Cloud. Requires `entity_id`. `dry_run: true` returns the Things
Cloud change payload without committing it.

### `list_headings`

Lists active headings, optionally filtered by project. Supported arguments:

- `project_id`: only include headings in this Things project id.
- `limit`: maximum number of returned rows. Defaults to `100`.

### `create_heading`

Creates a heading inside a project. Supported arguments:

- `title`: required heading title.
- `project_id`: required Things project id.
- `dry_run`: when `true`, returns the Things Cloud change payload without
  committing it.

### `update_heading`

Updates a heading. Supported arguments:

- `entity_id`: required Things heading id.
- `title`: replaces the title when provided.
- `notes`: replaces the note text when provided.
- `project_id`: moves the heading to this Things project.
- `tag_ids`: replaces the full tag id list when provided.
- `clear_notes` / `clear_tags`: clears the corresponding field.
- `dry_run`: when `true`, returns the Things Cloud change payload without
  committing it.

### `list_areas`

Lists Things areas by status and creation date. Supported arguments:

- `status`: `open`, `trashed`, `deleted`, or `all`. Defaults to `open`.
- `created_from` / `created_to`: filter by creation date.
- `limit`: maximum number of returned rows. Defaults to `100`.

Results are ordered by title.

### `create_area`

Creates a Things area. Supported arguments:

- `title`: required area title.
- `tag_ids`: Things tag entity ids. Duplicate ids are removed while preserving
  order.
- `dry_run`: when `true`, returns the Things Cloud change payload without
  committing it.

### `update_area`

Updates a Things area. Supported arguments:

- `entity_id`: required Things area id.
- `title`: replaces the title when provided.
- `tag_ids`: replaces the full tag id list when provided.
- `clear_tags`: clears all tags.
- `dry_run`: when `true`, returns the Things Cloud change payload without
  committing it.

### `delete_area`

Deletes a Things area using the tombstone-style Things Cloud delete payload.
Requires `entity_id`. `dry_run: true` returns the Things Cloud change payload
without committing it.

### `list_tags`

Lists Things tags by status and creation date. Supported arguments:

- `status`: `open`, `trashed`, `deleted`, or `all`. Defaults to `open`.
- `created_from` / `created_to`: filter by creation date.
- `limit`: maximum number of returned rows. Defaults to `100`.

Results are ordered by title.

### `create_tag`

Creates a Things tag. Supported arguments:

- `title`: required tag title.
- `parent_id`: optional parent Things tag id.
- `dry_run`: when `true`, returns the Things Cloud change payload without
  committing it.

### `update_tag`

Updates a Things tag. Supported arguments:

- `entity_id`: required Things tag id.
- `title`: replaces the title when provided.
- `parent_id`: moves the tag under this parent tag.
- `clear_parent`: removes the parent tag.
- `dry_run`: when `true`, returns the Things Cloud change payload without
  committing it.

### `delete_tag`

Deletes a Things tag using a tombstone-style Things Cloud delete payload.
Requires `entity_id`. `dry_run: true` returns the Things Cloud change payload
without committing it.
