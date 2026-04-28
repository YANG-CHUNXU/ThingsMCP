from __future__ import annotations

import importlib.util
import plistlib
import sqlite3
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "detect_history_key.py"
SPEC = importlib.util.spec_from_file_location("detect_history_key", SCRIPT_PATH)
assert SPEC is not None
detect_history_key = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(detect_history_key)


def test_read_sync_metadata_detects_email_history_key_and_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "main.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("create table BSSyncronyMetadata (uuid text, value blob)")
        values = [
            ("email", "user@example.com"),
            ("history", "12345678-1234-1234-1234-123456789abc"),
            ("index-1", 12),
            ("index-2", 12),
            ("index-3", 14),
        ]
        conn.executemany(
            "insert into BSSyncronyMetadata (uuid, value) values (?, ?)",
            [(key, plistlib.dumps(value)) for key, value in values],
        )

    metadata = detect_history_key.read_sync_metadata(db_path)

    assert metadata == {
        "db_path": str(db_path),
        "email": "user@example.com",
        "history_key": "12345678-1234-1234-1234-123456789abc",
        "sync_indexes": [12, 14],
    }
