"""Everything the web app and the CLI do to the database goes through here."""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
STAFF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,19}$")
ANSWERS = ("ok", "fail", "na")


class LogError(ValueError):
    """A user mistake the UI or CLI should show as a message."""


@dataclass
class Due:
    code: str
    equipment: str
    task_id: int
    title: str
    interval_days: int
    due_on: date
    days: int  # negative = overdue by that many days

    @property
    def overdue(self) -> bool:
        return self.days < 0


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _clean(value: str, field: str, limit: int = 200, required: bool = True) -> str:
    value = (value or "").strip()
    if required and not value:
        raise LogError(f"{field} is required.")
    if len(value) > limit:
        raise LogError(f"{field} is longer than {limit} characters.")
    return value


def _staff(value: str) -> str:
    value = (value or "").strip()
    if not STAFF_RE.match(value):
        raise LogError("Staff ID must be 1-20 letters, digits, dots, dashes or underscores (for example S-104).")
    return value


def parse_day(value: str | date, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        raise LogError(f"{field} must be a date like 2026-11-23.") from None


# Equipment


def add_equipment(conn: sqlite3.Connection, code: str, name: str, kind: str, location: str, now: datetime) -> None:
    code = (code or "").strip().upper()
    if not CODE_RE.match(code):
        raise LogError("Code must be 1-32 letters, digits, dots, dashes or underscores, for example FL-03.")
    name = _clean(name, "Name", 80)
    kind = _clean(kind, "Kind", 40).lower()
    location = _clean(location, "Location", 80, required=False)
    try:
        with conn:
            conn.execute(
                "INSERT INTO equipment (code, name, kind, location, created_at) VALUES (?, ?, ?, ?, ?)",
                (code, name, kind, location, _stamp(now)),
            )
    except sqlite3.IntegrityError:
        raise LogError(f"Equipment {code} already exists.") from None


def get_equipment(conn: sqlite3.Connection, code: str) -> sqlite3.Row:
    """Codes are stored in upper case, so FL-03 and fl-03 are the same equipment."""
    code = (code or "").strip().upper()
    row = conn.execute("SELECT * FROM equipment WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise LogError(f"No equipment with code {code}.")
    return row


def list_equipment(conn: sqlite3.Connection, today: date, query: str = "") -> list[dict]:
    """Equipment with its last check and whether it was checked today, filtered by a search text.

    A check made before the equipment was last returned to service does not count: after a repair it needs a new one.
    """
    like = f"%{query.strip()}%"
    rows = conn.execute(
        """
        SELECT e.*,
            (SELECT MAX(performed_at) FROM inspection i WHERE i.equipment_id = e.id) AS last_check,
            (SELECT MAX(recorded_at) FROM maintenance_record r
             WHERE r.equipment_id = e.id AND r.returned_to_service = 1) AS last_return
        FROM equipment e
        WHERE e.code LIKE ? OR e.name LIKE ? OR e.kind LIKE ? OR e.location LIKE ?
        ORDER BY e.kind, e.code
        """,
        (like, like, like, like),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        last_check, last_return = row["last_check"], row["last_return"]
        item["checked_today"] = (
            bool(last_check) and last_check[:10] == today.isoformat() and (not last_return or last_check > last_return)
        )
        result.append(item)
    return result


def take_out_of_service(conn: sqlite3.Connection, code: str, reason: str, now: datetime) -> None:
    equipment = get_equipment(conn, code)
    reason = _clean(reason, "Reason")
    if equipment["out_of_service"]:
        raise LogError(f"{code} is already out of service.")
    with conn:
        conn.execute(
            "UPDATE equipment SET out_of_service = 1, out_of_service_reason = ?, out_of_service_since = ? WHERE id = ?",
            (reason, _stamp(now), equipment["id"]),
        )


def return_to_service(conn: sqlite3.Connection, code: str, done_by: str, notes: str, now: datetime) -> None:
    """Back in service only with a maintenance record saying what was fixed and by whom."""
    equipment = get_equipment(conn, code)
    if not equipment["out_of_service"]:
        raise LogError(f"{code} is not out of service.")
    done_by = _staff(done_by)
    notes = _clean(notes, "What was fixed", 500)
    with conn:
        conn.execute(
            "INSERT INTO maintenance_record (equipment_id, done_on, done_by, notes, returned_to_service, recorded_at)"
            " VALUES (?, ?, ?, ?, 1, ?)",
            (equipment["id"], now.date().isoformat(), done_by, notes, _stamp(now)),
        )
        conn.execute(
            "UPDATE equipment SET out_of_service = 0, out_of_service_reason = '', out_of_service_since = NULL"
            " WHERE id = ?",
            (equipment["id"],),
        )


# Checklists


def import_checklists(conn: sqlite3.Connection, data: dict) -> list[str]:
    """Load checklists from parsed TOML: [checklists.<kind>] title = "...", items = ["text" | {text, critical}].

    Re-importing a kind replaces its items. Past inspections keep the item text they were answered with.
    """
    checklists = data.get("checklists")
    if not isinstance(checklists, dict) or not checklists:
        raise LogError("The file has no [checklists.<kind>] tables.")
    loaded = []
    with conn:
        for kind, table in checklists.items():
            kind = _clean(str(kind), "Checklist kind", 40).lower()
            if not isinstance(table, dict):
                raise LogError(f"checklists.{kind} must be a table.")
            title = _clean(str(table.get("title", "")), f"checklists.{kind}.title", 80)
            items = table.get("items")
            if not isinstance(items, list) or not items:
                raise LogError(f"checklists.{kind}.items must be a non-empty list.")
            parsed = []
            for n, item in enumerate(items, 1):
                if isinstance(item, str):
                    text, critical = item, False
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    text, critical = item["text"], item.get("critical", False)
                    if not isinstance(critical, bool):
                        raise LogError(f"checklists.{kind}.items[{n}].critical must be true or false.")
                else:
                    raise LogError(
                        f"checklists.{kind}.items[{n}] must be a string or {{ text = ..., critical = ... }}."
                    )
                parsed.append((_clean(text, f"checklists.{kind}.items[{n}]", 200), critical))
            conn.execute(
                "INSERT INTO checklist (kind, title) VALUES (?, ?)"
                " ON CONFLICT (kind) DO UPDATE SET title = excluded.title",
                (kind, title),
            )
            checklist_id = conn.execute("SELECT id FROM checklist WHERE kind = ?", (kind,)).fetchone()[0]
            conn.execute("DELETE FROM checklist_item WHERE checklist_id = ?", (checklist_id,))
            conn.executemany(
                "INSERT INTO checklist_item (checklist_id, position, text, critical) VALUES (?, ?, ?, ?)",
                [(checklist_id, pos, text, int(crit)) for pos, (text, crit) in enumerate(parsed, 1)],
            )
            loaded.append(kind)
    return loaded


def checklist_for(conn: sqlite3.Connection, kind: str) -> tuple[str, list[sqlite3.Row]]:
    row = conn.execute("SELECT id, title FROM checklist WHERE kind = ?", (kind,)).fetchone()
    if row is None:
        return "", []
    items = conn.execute(
        "SELECT id, text, critical FROM checklist_item WHERE checklist_id = ? AND active = 1 ORDER BY position",
        (row["id"],),
    ).fetchall()
    return row["title"], items


# Inspections


def record_inspection(
    conn: sqlite3.Connection, code: str, inspector: str, answers: dict[int, str], notes: str, now: datetime
) -> dict:
    """Save a pre-use check. A failed critical item takes the equipment out of service.

    Returns {"id", "passed", "failed": [texts], "taken_out": bool}.
    """
    equipment = get_equipment(conn, code)
    inspector = _staff(inspector)
    notes = _clean(notes, "Notes", 500, required=False)
    _, items = checklist_for(conn, equipment["kind"])
    if not items:
        raise LogError(f"There is no checklist for kind '{equipment['kind']}'. Import one first.")
    missing = [item["text"] for item in items if answers.get(item["id"]) not in ANSWERS]
    if missing:
        raise LogError("Answer every item. Missing: " + "; ".join(missing))
    failed = [item for item in items if answers[item["id"]] == "fail"]
    critical_failed = [item["text"] for item in failed if item["critical"]]
    if failed and not notes:
        raise LogError("Describe the problem in the notes when an item fails.")
    passed = not critical_failed
    taken_out = bool(critical_failed) and not equipment["out_of_service"]
    with conn:
        cur = conn.execute(
            "INSERT INTO inspection (equipment_id, inspector, performed_at, passed, notes) VALUES (?, ?, ?, ?, ?)",
            (equipment["id"], inspector, _stamp(now), int(passed), notes),
        )
        conn.executemany(
            "INSERT INTO inspection_answer (inspection_id, item_text, critical, answer, position)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                (cur.lastrowid, item["text"], item["critical"], answers[item["id"]], pos)
                for pos, item in enumerate(items, 1)
            ],
        )
        if taken_out:
            conn.execute(
                "UPDATE equipment SET out_of_service = 1, out_of_service_reason = ?, out_of_service_since = ?"
                " WHERE id = ?",
                ("Failed pre-use check: " + "; ".join(critical_failed), _stamp(now), equipment["id"]),
            )
    return {
        "id": cur.lastrowid,
        "passed": passed,
        "failed": [item["text"] for item in failed],
        "taken_out": taken_out,
    }


# Scheduled maintenance


def add_task(conn: sqlite3.Connection, code: str, title: str, interval_days: int | str, last_done: str = "") -> int:
    equipment = get_equipment(conn, code)
    title = _clean(title, "Task", 120)
    try:
        interval = int(interval_days)
    except (TypeError, ValueError):
        raise LogError("Interval must be a whole number of days.") from None
    if not 1 <= interval <= 3660:
        raise LogError("Interval must be between 1 and 3660 days.")
    last = parse_day(last_done, "Last done").isoformat() if (last_done or "").strip() else None
    with conn:
        cur = conn.execute(
            "INSERT INTO maintenance_task (equipment_id, title, interval_days, last_done) VALUES (?, ?, ?, ?)",
            (equipment["id"], title, interval, last),
        )
    return int(cur.lastrowid or 0)


def complete_task(
    conn: sqlite3.Connection, task_id: int, done_on: str | date, done_by: str, notes: str, now: datetime
) -> None:
    task = conn.execute("SELECT * FROM maintenance_task WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        raise LogError(f"No maintenance task {task_id}.")
    day = parse_day(done_on, "Done on")
    if day > now.date():
        raise LogError("Done on cannot be in the future.")
    done_by = _staff(done_by)
    notes = _clean(notes, "Notes", 500, required=False)
    # A late entry for an older date must not move the next due date backwards.
    last = max(filter(None, [task["last_done"], day.isoformat()]))
    with conn:
        conn.execute(
            "INSERT INTO maintenance_record (equipment_id, task_id, done_on, done_by, notes, recorded_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (task["equipment_id"], task_id, day.isoformat(), done_by, notes, _stamp(now)),
        )
        conn.execute("UPDATE maintenance_task SET last_done = ? WHERE id = ?", (last, task_id))


def tasks_for(conn: sqlite3.Connection, code: str, today: date) -> list[Due]:
    code = (code or "").strip().upper()
    return [d for d in due_list(conn, today, within_days=None) if d.code == code]


def due_list(conn: sqlite3.Connection, today: date, within_days: int | None = 7) -> list[Due]:
    """Tasks due within `within_days` (overdue included), soonest first. None = every task.

    A task never done is due today.
    """
    rows = conn.execute(
        """
        SELECT t.id, t.title, t.interval_days, t.last_done, e.code, e.name
        FROM maintenance_task t JOIN equipment e ON e.id = t.equipment_id
        """
    ).fetchall()
    result = []
    for row in rows:
        if row["last_done"]:
            due_on = date.fromisoformat(row["last_done"]) + timedelta(days=row["interval_days"])
        else:
            due_on = today
        days = (due_on - today).days
        if within_days is None or days <= within_days:
            result.append(Due(row["code"], row["name"], row["id"], row["title"], row["interval_days"], due_on, days))
    result.sort(key=lambda d: (d.due_on, d.code, d.title))
    return result


# History and export


def history(conn: sqlite3.Connection, code: str, limit: int = 50) -> list[dict]:
    """Inspections and maintenance records for one piece of equipment, newest first."""
    equipment = get_equipment(conn, code)
    events = []
    for row in conn.execute(
        "SELECT * FROM inspection WHERE equipment_id = ? ORDER BY performed_at DESC, id DESC LIMIT ?",
        (equipment["id"], limit),
    ):
        failed = [
            a["item_text"]
            for a in conn.execute(
                "SELECT item_text FROM inspection_answer WHERE inspection_id = ? AND answer = 'fail' ORDER BY position",
                (row["id"],),
            )
        ]
        events.append(
            {
                "when": row["performed_at"][:16],
                "order": (row["performed_at"][:10], row["performed_at"], 0),
                "type": "check",
                "who": row["inspector"],
                "summary": ("passed" if row["passed"] else "FAILED")
                + (f", defects: {'; '.join(failed)}" if failed else ""),
                "notes": row["notes"],
            }
        )
    for row in conn.execute(
        """
        SELECT r.*, t.title FROM maintenance_record r LEFT JOIN maintenance_task t ON t.id = r.task_id
        WHERE r.equipment_id = ? ORDER BY r.done_on DESC, r.id DESC LIMIT ?
        """,
        (equipment["id"], limit),
    ):
        summary = row["title"] or "repair"
        if row["returned_to_service"]:
            summary += ", returned to service"
        events.append(
            {
                "when": row["done_on"],
                "order": (row["done_on"], row["recorded_at"], 1),
                "type": "maintenance",
                "who": row["done_by"],
                "summary": summary,
                "notes": row["notes"],
            }
        )
    # Same day: in the order they were entered (same second: the repair after the check that found the fault).
    # A late entry for an earlier day stays on that day.
    events.sort(key=lambda e: e["order"], reverse=True)
    return events[:limit]


def _cell(value: object) -> object:
    # Spreadsheet apps run cells starting with these as formulas.
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def inspections_csv(conn: sqlite3.Connection, since: date, until: date) -> str:
    """One row per answered item between two dates (inclusive), for audits."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["performed_at", "code", "equipment", "inspector", "passed", "item", "critical", "answer", "notes"])
    rows = conn.execute(
        """
        SELECT i.performed_at, e.code, e.name, i.inspector, i.passed, a.item_text, a.critical, a.answer, i.notes
        FROM inspection i
        JOIN equipment e ON e.id = i.equipment_id
        JOIN inspection_answer a ON a.inspection_id = i.id
        WHERE substr(i.performed_at, 1, 10) BETWEEN ? AND ?
        ORDER BY i.performed_at, e.code, a.position
        """,
        (since.isoformat(), until.isoformat()),
    )
    for row in rows:
        writer.writerow(
            [_cell(v) for v in (row[0], row[1], row[2], row[3], "yes" if row[4] else "no", row[5])]
            + ["yes" if row[6] else "no", row[7], _cell(row[8])]
        )
    return out.getvalue()
