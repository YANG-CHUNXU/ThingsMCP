#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import plistlib
import re
import sqlite3
from pathlib import Path
from typing import Any


GROUP_CONTAINER = Path.home() / "Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac"


def find_things_database() -> Path | None:
    candidates = sorted(
        GROUP_CONTAINER.glob("ThingsData-*/Things Database.thingsdatabase/main.sqlite"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def read_sync_metadata(db_path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "db_path": str(db_path),
        "email": None,
        "history_key": None,
        "sync_indexes": [],
    }
    if not db_path.exists():
        return metadata

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        rows = conn.execute("select uuid, value from BSSyncronyMetadata").fetchall()

    strings: list[str] = []
    ints: list[int] = []
    for _, blob in rows:
        try:
            value = plistlib.loads(blob)
        except Exception:
            continue
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, int):
            ints.append(value)

    emails = [value for value in strings if "@" in value]
    uuid_like = [
        value
        for value in strings
        if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value)
    ]
    metadata["email"] = emails[0] if emails else None
    metadata["history_key"] = uuid_like[0] if uuid_like else None
    metadata["sync_indexes"] = sorted(set(ints))
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect local Things Cloud account metadata.")
    parser.add_argument("--db", default=None, help="Path to Things main.sqlite. Auto-detected by default.")
    parser.add_argument("--show-metadata", action="store_true", help="Print email, history key, sync indexes, and DB path.")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON.")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser() if args.db else find_things_database()
    if db_path is None:
        raise SystemExit(
            "Could not find the local Things database. Use --db to pass the path to main.sqlite."
        )

    metadata = read_sync_metadata(db_path)
    if args.json or args.show_metadata:
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return 0 if metadata.get("history_key") else 1

    history_key = metadata.get("history_key")
    if not history_key:
        raise SystemExit("Could not detect a Things Cloud history key from the local metadata.")
    print(history_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
