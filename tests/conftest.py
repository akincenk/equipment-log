import tomllib
from datetime import datetime
from pathlib import Path

import pytest

from equipment_log import store
from equipment_log.db import open_db

EXAMPLES = Path(__file__).parent.parent / "examples"
NOW = datetime(2026, 11, 23, 7, 30)


@pytest.fixture
def conn(tmp_path):
    conn = open_db(tmp_path / "log.db")
    with open(EXAMPLES / "checklists.toml", "rb") as fh:
        store.import_checklists(conn, tomllib.load(fh))
    store.add_equipment(conn, "FL-03", "Reach truck 3", "forklift", "Dock B", NOW)
    store.add_equipment(conn, "LD-01", "Rolling stair 1", "ladder", "Aisle 4", NOW)
    yield conn
    conn.close()


def answers(conn, code, fail=()):
    """All items OK except those whose text starts with one of `fail`."""
    kind = store.get_equipment(conn, code)["kind"]
    _, items = store.checklist_for(conn, kind)
    return (
        {item["id"]: ("fail" if item["text"].startswith(tuple(fail)) else "ok") for item in items}
        if fail
        else {item["id"]: "ok" for item in items}
    )
