from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_BASE_URL = "https://cloud.culturedcode.com/"
DEFAULT_TIMEZONE = "UTC"
THINGS_MAC_BUNDLE_ID = "com.culturedcode.ThingsMac"
THINGS_MAC_APP_PATH = Path("/Applications/Things3.app")
THINGS_MAC_CACHE_DIR = (
    Path.home()
    / "Library/Containers/com.culturedcode.ThingsMac/Data/Library/Caches/com.culturedcode.ThingsMac"
)


class ConfigError(RuntimeError):
    pass


class ThingsCloudError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class ThingsConfig:
    email: str
    password: str
    history_key: str
    base_url: str = DEFAULT_BASE_URL
    timezone: str = DEFAULT_TIMEZONE
    app_id: str = "com.culturedcode.ThingsMac"
    app_instance_id: str | None = None
    push_priority: int = 5

    @classmethod
    def from_env(cls) -> "ThingsConfig":
        missing = [
            name
            for name in ["THINGS_CLOUD_EMAIL", "THINGS_CLOUD_PASSWORD", "THINGS_CLOUD_HISTORY_KEY"]
            if not os.environ.get(name)
        ]
        if missing:
            raise ConfigError("Missing required environment variables: " + ", ".join(missing))
        timezone = os.environ.get("THINGS_TIMEZONE", DEFAULT_TIMEZONE)
        validate_timezone(timezone)
        return cls(
            email=os.environ["THINGS_CLOUD_EMAIL"],
            password=os.environ["THINGS_CLOUD_PASSWORD"],
            history_key=os.environ["THINGS_CLOUD_HISTORY_KEY"],
            base_url=os.environ.get("THINGS_CLOUD_BASE_URL", DEFAULT_BASE_URL),
            timezone=timezone,
            app_id=os.environ.get("THINGS_MCP_APP_ID", "com.culturedcode.ThingsMac"),
            app_instance_id=os.environ.get("THINGS_MCP_APP_INSTANCE_ID"),
            push_priority=parse_push_priority(os.environ.get("THINGS_MCP_PUSH_PRIORITY", "5")),
        )


class ThingsCloudClient:
    def __init__(self, config: ThingsConfig, timeout: int = 20) -> None:
        self.config = config
        self.timeout = timeout

    def history(self) -> dict[str, Any]:
        return self._request("GET", f"version/1/history/{self._history_key()}").body

    def history_items(self, start_index: int = 0) -> dict[str, Any]:
        path = f"version/1/history/{self._history_key()}/items?start-index={start_index}"
        return self._request("GET", path).body

    def commit(self, change_map: dict[str, Any], ancestor_index: int, schema: int) -> dict[str, Any] | None:
        path = f"version/1/history/{self._history_key()}/commit?ancestor-index={ancestor_index}&_cnt=1"
        return self._request("POST", path, body=change_map, extra_headers=self._write_headers(schema)).body

    def _history_key(self) -> str:
        return urllib.parse.quote(self.config.history_key, safe="")

    def _write_headers(self, schema: int) -> dict[str, str]:
        headers = {
            "Schema": str(schema),
            "App-Id": self.config.app_id,
            "Push-Priority": str(self.config.push_priority),
            "Content-Encoding": "UTF8",
        }
        headers.update(detect_things_client_headers() or fallback_client_headers())
        app_instance_id = self.config.app_instance_id or detect_app_instance_id(self.config.app_id)
        if app_instance_id:
            headers["App-Instance-Id"] = app_instance_id
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        extra_headers: dict[str, str] | None = None,
    ) -> "CloudResponse":
        url = urllib.parse.urljoin(self.config.base_url, path)
        headers = {
            "Accept": "application/json",
            "User-Agent": "ThingsMCP/0.1.0",
        }
        data = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=UTF-8"
        if extra_headers:
            headers.update(extra_headers)

        token = base64.b64encode(f"{self.config.email}:{self.config.password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                return CloudResponse(status=response.status, body=decode_body(payload), headers=dict(response.headers))
        except urllib.error.HTTPError as exc:
            payload = decode_body(exc.read())
            raise ThingsCloudError(
                f"Things Cloud returned HTTP {exc.code}",
                status=exc.code,
                body=payload,
            ) from exc
        except urllib.error.URLError as exc:
            raise ThingsCloudError(f"Could not reach Things Cloud: {exc.reason}", status=None) from exc


def fallback_client_headers() -> dict[str, str]:
    client_info = {
        "nativeAppName": "ThingsMCP",
        "nativeAppVersion": "0.1.0",
        "osName": "Linux",
        "developmentBuild": False,
    }
    encoded_info = base64.b64encode(
        json.dumps(client_info, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return {
        "things-client-info": encoded_info,
        "User-Agent": "ThingsMCP/0.1.0",
    }


def parse_push_priority(value: str) -> int:
    try:
        priority = int(value)
    except ValueError as exc:
        raise ConfigError("THINGS_MCP_PUSH_PRIORITY must be an integer from 0 to 10.") from exc
    if not 0 <= priority <= 10:
        raise ConfigError("THINGS_MCP_PUSH_PRIORITY must be an integer from 0 to 10.")
    return priority


def validate_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Invalid THINGS_TIMEZONE: {value}") from exc


def detect_app_instance_id(app_id: str) -> str | None:
    pattern = re.compile(rb"[0-9a-f]{64}-" + re.escape(app_id.encode("ascii")) + rb"-[0-9a-f]{64}")
    candidates: list[str] = []
    for path in [THINGS_MAC_CACHE_DIR / "Cache.db-wal", THINGS_MAC_CACHE_DIR / "Cache.db"]:
        if not path.exists():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        candidates.extend(match.decode("ascii") for match in pattern.findall(data))
    return sorted(set(candidates))[0] if candidates else None


def detect_things_client_headers() -> dict[str, str] | None:
    if not THINGS_MAC_APP_PATH.exists():
        return None
    version = (
        command_output(["defaults", "read", str(THINGS_MAC_APP_PATH / "Contents/Info.plist"), "CFBundleVersion"])
        or command_output(["defaults", "read", str(THINGS_MAC_APP_PATH / "Contents/Info.plist"), "CFBundleShortVersionString"])
        or "3.22"
    )
    os_version = command_output(["sw_vers", "-productVersion"])
    device_model = command_output(["sysctl", "-n", "hw.model"])
    user_locale = normalize_locale(command_output(["defaults", "read", "-g", "AppleLocale"]))
    preferred_language = normalize_locale(first_apple_language())
    region = region_from_locale(preferred_language) or region_from_locale(user_locale)

    client_info: dict[str, Any] = {
        "nf": True,
        "nk": True,
        "nn": "ThingsMac",
        "nv": version,
        "on": "macOS",
    }
    if os_version:
        client_info["ov"] = os_version
    if device_model:
        client_info["dm"] = device_model
    if region:
        client_info["lr"] = region
    if preferred_language:
        client_info["pl"] = preferred_language
    if user_locale:
        client_info["ul"] = user_locale

    encoded_info = base64.b64encode(
        json.dumps(client_info, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return {
        "things-client-info": encoded_info,
        "User-Agent": f"ThingsMac/{version}",
    }


def command_output(command: list[str]) -> str | None:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def first_apple_language() -> str | None:
    output = command_output(["defaults", "read", "-g", "AppleLanguages"])
    if not output:
        return None
    quoted = re.findall(r'"([^"]+)"', output)
    if quoted:
        return quoted[0]
    for line in output.splitlines():
        cleaned = line.strip().strip("(),")
        if cleaned:
            return cleaned
    return None


def normalize_locale(value: str | None) -> str | None:
    return value.replace("_", "-") if value else value


def region_from_locale(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.replace("_", "-").split("-")
    return parts[-1] if len(parts) > 1 and len(parts[-1]) == 2 else None


@dataclass(frozen=True)
class CloudResponse:
    status: int
    body: Any
    headers: dict[str, str]


def decode_body(payload: bytes) -> Any:
    if not payload:
        return None
    text = payload.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:2000]
