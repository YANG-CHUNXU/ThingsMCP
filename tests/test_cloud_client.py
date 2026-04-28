from __future__ import annotations

import base64
import io
import json
import urllib.error
from typing import Any

import pytest

from things_mcp import cloud_client
from things_mcp.cloud_client import ThingsCloudClient, ThingsCloudError, ThingsConfig


class FakeHTTPResponse:
    status = 200
    headers = {"content-type": "application/json"}

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_cloud_client_builds_history_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout: int):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        captured["timeout"] = timeout
        return FakeHTTPResponse(b'{"latest-server-index":42}')

    monkeypatch.setattr(cloud_client.urllib.request, "urlopen", fake_urlopen)
    client = ThingsCloudClient(ThingsConfig(email="me@example.com", password="secret", history_key="key/with space"), timeout=3)

    body = client.history()

    assert body == {"latest-server-index": 42}
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/version/1/history/key%2Fwith%20space")
    assert captured["headers"]["authorization"] == "Basic " + base64.b64encode(b"me@example.com:secret").decode("ascii")
    assert captured["timeout"] == 3


def test_cloud_client_commit_sends_json_and_write_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout: int):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        captured["data"] = request.data
        return FakeHTTPResponse(b'{"things-response":"OK"}')

    monkeypatch.setattr(cloud_client.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(cloud_client, "detect_things_client_headers", lambda: None)
    monkeypatch.setattr(cloud_client, "detect_app_instance_id", lambda app_id: None)
    client = ThingsCloudClient(
        ThingsConfig(email="e", password="p", history_key="h", app_instance_id="configured-id", push_priority=7)
    )

    body = client.commit({"task": {"t": 1, "e": "Task6", "p": {"tt": "Title"}}}, 12, 301)

    assert body == {"things-response": "OK"}
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/version/1/history/h/commit?ancestor-index=12&_cnt=1")
    assert json.loads(captured["data"]) == {"task": {"t": 1, "e": "Task6", "p": {"tt": "Title"}}}
    assert captured["headers"]["schema"] == "301"
    assert captured["headers"]["app-id"] == "com.culturedcode.ThingsMac"
    assert captured["headers"]["app-instance-id"] == "configured-id"
    assert captured["headers"]["push-priority"] == "7"


def test_cloud_client_decodes_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout: int):
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            {},
            io.BytesIO(b'{"error":"denied"}'),
        )

    monkeypatch.setattr(cloud_client.urllib.request, "urlopen", fake_urlopen)
    client = ThingsCloudClient(ThingsConfig(email="e", password="p", history_key="h"))

    with pytest.raises(ThingsCloudError) as exc_info:
        client.history_items(5)

    assert exc_info.value.status == 403
    assert exc_info.value.body == {"error": "denied"}
