FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY things_mcp ./things_mcp

RUN pip install --no-cache-dir .
RUN useradd --create-home --shell /usr/sbin/nologin things-mcp \
    && mkdir -p /data \
    && chown things-mcp:things-mcp /data

ENV THINGS_MCP_DB_PATH=/data/entities.sqlite
USER things-mcp

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=2).read()"
CMD ["sh", "-c", "if [ -z \"$THINGS_MCP_AUTH_TOKEN\" ] && [ \"$THINGS_MCP_ALLOW_UNAUTHENTICATED\" != \"true\" ]; then echo 'THINGS_MCP_AUTH_TOKEN is required unless THINGS_MCP_ALLOW_UNAUTHENTICATED=true.' >&2; exit 1; fi; exec things-mcp serve --host 0.0.0.0 --port 8765"]
