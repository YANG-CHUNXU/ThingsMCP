# ThingsMCP Agent Notes

## Development

- Run tests with `.venv/bin/pytest -q`.
- Do not commit or overwrite `.env`; it contains local deployment secrets.
- The local SQLite entities cache is a read-through cache for MCP query tools. Things Cloud remains the source of truth for writes.
- `THINGS_MCP_DB_PATH` can override the cache location.

## Deployment

- Keep deployment-specific hostnames, IP addresses, paths, credentials, and service configuration outside the public repository.
- Preserve any production `.env` file unless explicitly asked to change it.
- After deployment, verify service status, local port binding, `/healthz`, and recent service logs.
