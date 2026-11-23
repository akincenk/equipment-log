"""SQLite connection and a small numbered-migration runner."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrations() -> list[tuple[int, str, str]]:
    """Return (number, name, sql) for every bundled migration, in order."""
    found = []
    for entry in resources.files("equipment_log").joinpath("migrations").iterdir():
        if entry.name.endswith(".sql"):
            number = int(entry.name.split("_", 1)[0])
            found.append((number, entry.name, entry.read_text(encoding="utf-8")))
    found.sort()
    return found


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply migrations newer than the stored user_version. Returns the names applied."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    applied = []
    for number, name, sql in migrations():
        if number <= current:
            continue
        # executescript commits first; the user_version update is part of the same script.
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            raise
        applied.append(name)
    return applied


def open_db(path: str | Path) -> sqlite3.Connection:
    conn = connect(path)
    migrate(conn)
    return conn
