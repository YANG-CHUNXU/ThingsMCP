# ThingsMCP

[English](README.md) | [简体中文](README.zh-CN.md)

Things Cloud 的个人、非官方 MCP 服务器。它会直接与 Things Cloud 通信，并避免依赖 macOS 专属能力，因此可以运行在无头服务器或任何受支持的 Python 环境中。

## 重要说明

本项目是非官方项目，未获得 Cultured Code 支持，仅适合个人使用。它依赖未被文档化为公开 API 的 Things Cloud 行为，这些行为可能随时变化或失效。

使用 Things Cloud 的非公开 endpoint 可能违反 Cultured Code 的服务条款。请自行承担使用风险。请妥善保管凭据，只把服务绑定到可信网络接口，并在执行写操作前先使用 `dry_run` 测试。本项目不是稳定 SDK，也不应被用于提供托管或共享的 Things Cloud 服务。

本项目对 Things Cloud 写入行为没有经过完整验证。错误的写入 payload 可能会把无效数据同步到 Things Cloud，并导致官方 Things app 行为异常或崩溃。启用写操作前，请先做好 Things 数据备份。

## 配置

复制 `.env.example` 为 `.env`，并填写：

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

`history_key` 是 Things Cloud 账号元数据的一部分，需要和账号凭据一起通过配置提供。在已安装并同步 Things 的 Mac 上，通常可以从本地 Things 数据库中检测出来：

```bash
python scripts/detect_history_key.py --show-metadata
```

请把 `THINGS_TIMEZONE` 设置为你在 Things 中实际使用的 IANA 时区，例如 `America/New_York`、`Europe/Berlin` 或 `Asia/Shanghai`。如果省略该配置，ThingsMCP 会使用 `UTC`。

读取工具会维护一个本地 SQLite 缓存，用于保存折叠后的 Things 实体。默认路径是 `~/.cache/things-mcp/entities.sqlite`；可通过 `THINGS_MCP_DB_PATH` 覆盖。每个读取工具在查询缓存前都会先从 Things Cloud 同步。`THINGS_MCP_SYNC_TTL_SECONDS` 可以在短时间内跳过重复读取同步；默认值 `0` 是最稳妥的行为，即每次读取前都同步。如果同步失败但已有缓存，响应会包含 `stale: true` 和 `sync_error`。

请求体和 Things 写入 payload 默认会在日志中脱敏。只有在本地调试并确实需要完整 payload 日志时，才设置 `THINGS_MCP_LOG_PAYLOADS=true`。

## 运行

```bash
python -m pip install -e ".[test]"
things-mcp serve --host 127.0.0.1 --port 8765
```

MCP endpoint 是 `http://127.0.0.1:8765/mcp`。健康检查地址是 `http://127.0.0.1:8765/healthz`。

默认 host 只绑定本机。不要把这个服务直接暴露到公网。

默认必须设置 `THINGS_MCP_AUTH_TOKEN`。MCP 请求必须带上：

```http
Authorization: Bearer <token>
```

仅在本地实验时，可以设置 `THINGS_MCP_ALLOW_UNAUTHENTICATED=true` 以无 bearer token 运行。不要在任何网络可达的服务器上使用该模式。

## Docker

```bash
docker compose up --build
```

默认 compose 文件绑定到 `127.0.0.1:8765`，以非 root 用户运行，并把 SQLite 缓存保存在 Docker 命名卷中。

Docker 镜像在未设置 `THINGS_MCP_AUTH_TOKEN` 且未显式配置 `THINGS_MCP_ALLOW_UNAUTHENTICATED=true` 时会拒绝启动。

## 工具

所有工具响应都使用这个结构：

```json
{"ok": true, "data": "...", "error": null}
```

失败时 `ok: false`，并包含 `error.code` 和 `error.message`。读取工具会先从 Things Cloud 同步，再查询本地缓存。如果同步失败但已有缓存，响应会包含 `stale: true` 和 `sync_error`，并从本地缓存返回 `data`。

日期参数接受 `YYYY-MM-DD`、`today` 或 `tomorrow`。日期会按 `THINGS_TIMEZONE` 解释；未设置 `THINGS_TIMEZONE` 时使用 `UTC`。范围过滤是闭区间：`*_from` 是下界，`*_to` 是上界；两者使用同一天会返回该日期当天的项目。没有对应日期字段的项目在按该字段过滤时会被排除。

`limit` 默认是 `100`，必须在 `0` 到 `500` 之间。

如需 Things Today 风格的待办结果，请使用 `list_today_todos`，或调用 `list_todos` 并传入 `status: "open"` 和 `start_to: "today"`。类似 `start_from: "today"` 加 `start_to: "today"` 的精确范围只会匹配 Things 中 `When` 日期正好是今天的项目，会漏掉 Things Today 中仍会显示的、过去日期安排但尚未完成的项目。

待办和项目工具使用的状态值：

- `open`：未删除、未移入废纸篓、未完成、未取消。
- `archived`：已完成或已取消，但未删除、未移入废纸篓。
- `completed`：仅已完成/已进入日志簿。
- `trashed`：在废纸篓中，但未永久删除。
- `deleted`：已从折叠后的 Things 历史中删除。
- `all`：所有未永久删除项目，包括废纸篓和已归档项目。

区域和标签工具支持 `open`、`trashed`、`deleted` 和 `all`。

### `list_todos`

列出 Things 待办。支持参数：

- `status`：上面的状态值之一，默认 `open`。
- `project_id`：只包含属于该 Things 项目的待办。
- `area_id`：只包含属于该 Things 区域的待办。
- `tag_ids`：只包含同时拥有所有指定 Things 标签 id 的待办。
- `created_from` / `created_to`：按创建日期过滤。
- `start_from` / `start_to`：按 Things `When` / 安排日期过滤。
- `deadline_from` / `deadline_to`：按截止日期过滤。
- `limit`：最大返回行数，默认 `100`。

结果按修改时间倒序排列。

示例：Things Today 风格待办，包含今天以前安排但未完成的项目：

```json
{
  "status": "open",
  "start_to": "today"
}
```

示例：Things 中 `When` 日期正好是今天的待办：

```json
{
  "status": "open",
  "start_from": "today",
  "start_to": "today"
}
```

示例：今天或更早到期的待办：

```json
{
  "status": "open",
  "deadline_to": "today"
}
```

### `list_today_todos`

列出应出现在 Things Today 风格视图中的 open 待办。它返回 Things `When` / 安排日期为今天或更早的待办，因此会包含过去日期安排但尚未完成的项目。没有 Things `When` / 安排日期的待办不会包含在内。

支持参数：

- `project_id`：只包含属于该 Things 项目的待办。
- `area_id`：只包含属于该 Things 区域的待办。
- `tag_ids`：只包含同时拥有所有指定 Things 标签 id 的待办。
- `limit`：最大返回行数，默认 `100`。

等价的 `list_todos` 调用：

```json
{
  "status": "open",
  "start_to": "today"
}
```

### `list_inbox_todos`

列出 Things Inbox 中的 open 待办。支持参数：

- `tag_ids`：只包含同时拥有所有指定 Things 标签 id 的待办。
- `limit`：最大返回行数，默认 `100`。

### `list_upcoming_todos`

列出默认从明天开始的已安排 open 待办。支持参数：

- `start_from`：安排日期下界，默认 `tomorrow`。
- `start_to`：安排日期上界。
- `tag_ids`：只包含同时拥有所有指定 Things 标签 id 的待办。
- `limit`：最大返回行数，默认 `100`。

### `list_deadline_todos`

列出有截止日期的 open 待办。支持参数：

- `deadline_from` / `deadline_to`：按截止日期过滤。
- `tag_ids`：只包含同时拥有所有指定 Things 标签 id 的待办。
- `limit`：最大返回行数，默认 `100`。

### `list_logbook_todos`

列出已完成或已取消的待办。支持参数：

- `limit`：最大返回行数，默认 `100`。

### `search_todos`

按标题和纯文本备注搜索 Things 待办。查询不区分大小写，去掉首尾空白后不能为空。支持参数：

- `query`：搜索文本。
- `status`：上面的待办状态值之一，默认 `all`。
- `created_from` / `created_to`：按创建日期过滤。
- `deadline_from` / `deadline_to`：按截止日期过滤。
- `limit`：最大返回行数，默认 `100`。

该工具不支持 `start_from` / `start_to`；如需按 Things `When` / 安排日期查询，请使用 `list_todos`。

### `search_projects`

按标题和纯文本备注搜索 Things 项目。支持参数：

- `query`：搜索文本，去掉首尾空白后不能为空。
- `status`：上面的待办/项目状态值之一，默认 `all`。
- `limit`：最大返回行数，默认 `100`。

### `search_tags`

按标题搜索 Things 标签。支持参数：

- `query`：搜索文本，去掉首尾空白后不能为空。
- `status`：`open`、`trashed`、`deleted` 或 `all`，默认 `all`。
- `limit`：最大返回行数，默认 `100`。

### `get_item`

按 `entity_id` 返回一个折叠后的 Things 实体。该 id 可以指向待办、项目、区域、标签或其他已同步的 Things 实体。如果折叠状态中不存在该 id，则返回 `null` 数据。

### `create_todo`

在 Inbox 中创建 Things 待办。支持参数：

- `title`：必填，待办标题。
- `notes`：备注文本；接受 Things 备注支持的 Markdown 风格标记。
- `when`：Things `When` / 安排日期。
- `reminder_time`：安排日期上的提醒时间，格式为 `HH:MM`，以 5 分钟为增量。需要同时提供 `when` 或 `list_name: "today"`。
- `deadline`：截止日期。
- `tag_ids`：Things 标签实体 id。重复 id 会在保持顺序的同时移除。
- `checklist_items`：附加到新待办的检查清单项目标题。
- `project_id`：在该 Things 项目中创建待办。
- `area_id`：在该 Things 区域中创建待办。
- `list_name`：在内置列表中创建待办：`inbox`、`today`、`anytime`、`someday` 或 `logbook`。
- `dry_run`：为 `true` 时返回 Things Cloud change payload，但不提交。

### `update_todo`

更新现有 Things 待办的指定字段。支持参数：

- `entity_id`：必填，Things 待办 id。
- `title`：提供时替换标题。
- `notes`：提供时替换备注文本；接受 Things 备注支持的 Markdown 风格标记。
- `when`：提供时替换 Things `When` / 安排日期。
- `reminder_time`：替换待办安排日期上的提醒时间，格式为 `HH:MM`，以 5 分钟为增量。使用 `clear_reminder: true` 可移除提醒。
- `deadline`：提供时替换截止日期。
- `tag_ids`：提供时替换完整标签 id 列表。重复 id 会在保持顺序的同时移除。
- `project_id`：将待办移动到该 Things 项目。
- `area_id`：将待办移动到该 Things 区域。
- `list_name`：将待办移动到内置列表：`inbox`、`today`、`anytime`、`someday` 或 `logbook`。
- `clear_notes` / `clear_when` / `clear_reminder` / `clear_deadline` / `clear_tags`：清除对应字段。
- `dry_run`：为 `true` 时返回 Things Cloud change payload，但不提交。

只会修改提供且非 null 的字段。至少需要提供一个可修改字段。

### `complete_todo`

将 Things 待办标记为已完成，使其进入 Things Logbook。需要 `entity_id`。`dry_run: true` 会返回 Things Cloud change payload，但不提交。

### `cancel_todo`

将 Things 待办标记为已取消。需要 `entity_id`。`dry_run: true` 会返回 Things Cloud change payload，但不提交。

### `delete_todo`

将 Things 待办移动到废纸篓。这是软删除，不是从 Things Cloud 永久删除。需要 `entity_id`。`dry_run: true` 会返回 Things Cloud change payload，但不提交。

### `list_projects`

按状态、创建日期和截止日期列出 Things 项目。支持参数：

- `status`：上面的待办/项目状态值之一，默认 `open`。
- `created_from` / `created_to`：按创建日期过滤。
- `deadline_from` / `deadline_to`：按项目截止日期过滤。
- `limit`：最大返回行数，默认 `100`。

结果按标题排序。返回的项目会包含 `archived` 和 `in_logbook` 标记，用于表示项目是否已进入 Things Logbook。

### `create_project`

创建 Things 项目。支持参数：

- `title`：必填，项目标题。
- `notes`：项目备注文本。
- `when`：Things `When` / 安排日期。
- `deadline`：项目截止日期。
- `area_ids`：Things 区域实体 id。重复 id 会在保持顺序的同时移除。
- `tag_ids`：Things 标签实体 id。重复 id 会在保持顺序的同时移除。
- `dry_run`：为 `true` 时返回 Things Cloud change payload，但不提交。

### `update_project`

更新现有 Things 项目的指定字段。支持参数：

- `entity_id`：必填，Things 项目 id。
- `title`：提供时替换标题。
- `notes`：提供时替换备注文本。
- `when`：提供时替换 Things `When` / 安排日期。
- `deadline`：提供时替换截止日期。
- `area_ids`：提供时替换完整区域 id 列表。
- `tag_ids`：提供时替换完整标签 id 列表。
- `clear_notes` / `clear_when` / `clear_deadline` / `clear_area` / `clear_tags`：清除对应字段。
- `dry_run`：为 `true` 时返回 Things Cloud change payload，但不提交。

### `complete_project`

将 Things 项目标记为已完成，并归档未完成的子任务和标题。需要 `entity_id`。`dry_run: true` 会返回 Things Cloud change payload，但不提交。

### `cancel_project`

将 Things 项目标记为已取消，并取消未完成的子任务和标题。需要 `entity_id`。`dry_run: true` 会返回 Things Cloud change payload，但不提交。

### `delete_project`

将 Things 项目移动到废纸篓。这是软删除，不是从 Things Cloud 永久删除。需要 `entity_id`。`dry_run: true` 会返回 Things Cloud change payload，但不提交。

### `list_headings`

列出 active 标题，可按项目过滤。支持参数：

- `project_id`：只包含该 Things 项目中的标题。
- `limit`：最大返回行数，默认 `100`。

### `create_heading`

在项目中创建标题。支持参数：

- `title`：必填，标题文本。
- `project_id`：必填，Things 项目 id。
- `dry_run`：为 `true` 时返回 Things Cloud change payload，但不提交。

### `update_heading`

更新标题。支持参数：

- `entity_id`：必填，Things 标题 id。
- `title`：提供时替换标题。
- `notes`：提供时替换备注文本。
- `project_id`：将标题移动到该 Things 项目。
- `tag_ids`：提供时替换完整标签 id 列表。
- `clear_notes` / `clear_tags`：清除对应字段。
- `dry_run`：为 `true` 时返回 Things Cloud change payload，但不提交。

### `list_areas`

按状态和创建日期列出 Things 区域。支持参数：

- `status`：`open`、`trashed`、`deleted` 或 `all`，默认 `open`。
- `created_from` / `created_to`：按创建日期过滤。
- `limit`：最大返回行数，默认 `100`。

结果按标题排序。

### `create_area`

创建 Things 区域。支持参数：

- `title`：必填，区域标题。
- `tag_ids`：Things 标签实体 id。重复 id 会在保持顺序的同时移除。
- `dry_run`：为 `true` 时返回 Things Cloud change payload，但不提交。

### `update_area`

更新 Things 区域。支持参数：

- `entity_id`：必填，Things 区域 id。
- `title`：提供时替换标题。
- `tag_ids`：提供时替换完整标签 id 列表。
- `clear_tags`：清除所有标签。
- `dry_run`：为 `true` 时返回 Things Cloud change payload，但不提交。

### `delete_area`

使用 tombstone 风格的 Things Cloud delete payload 删除 Things 区域。需要 `entity_id`。`dry_run: true` 会返回 Things Cloud change payload，但不提交。

### `list_tags`

按状态和创建日期列出 Things 标签。支持参数：

- `status`：`open`、`trashed`、`deleted` 或 `all`，默认 `open`。
- `created_from` / `created_to`：按创建日期过滤。
- `limit`：最大返回行数，默认 `100`。

结果按标题排序。

### `create_tag`

创建 Things 标签。支持参数：

- `title`：必填，标签标题。
- `parent_id`：可选，父级 Things 标签 id。
- `dry_run`：为 `true` 时返回 Things Cloud change payload，但不提交。

### `update_tag`

更新 Things 标签。支持参数：

- `entity_id`：必填，Things 标签 id。
- `title`：提供时替换标题。
- `parent_id`：将标签移动到该父标签下。
- `clear_parent`：移除父标签。
- `dry_run`：为 `true` 时返回 Things Cloud change payload，但不提交。

### `delete_tag`

使用 tombstone 风格的 Things Cloud delete payload 删除 Things 标签。需要 `entity_id`。`dry_run: true` 会返回 Things Cloud change payload，但不提交。
