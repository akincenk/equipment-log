from datetime import date, datetime

import pytest
from conftest import NOW, answers

from equipment_log import store
from equipment_log.db import migrate, migrations


def test_migrations_are_numbered_and_idempotent(conn):
    numbers = [n for n, _, _ in migrations()]
    assert numbers == sorted(set(numbers))
    assert migrate(conn) == []
    assert conn.execute("PRAGMA user_version").fetchone()[0] == numbers[-1]


def test_add_equipment_validates_code_and_duplicates(conn):
    with pytest.raises(store.LogError, match="already exists"):
        store.add_equipment(conn, "FL-03", "Another", "forklift", "", NOW)
    with pytest.raises(store.LogError, match="Code must be"):
        store.add_equipment(conn, "FL 03", "Space in code", "forklift", "", NOW)
    with pytest.raises(store.LogError, match="Name is required"):
        store.add_equipment(conn, "FL-04", " ", "forklift", "", NOW)


def test_passing_check(conn):
    result = store.record_inspection(conn, "FL-03", "S-104", answers(conn, "FL-03"), "", NOW)
    assert result["passed"] and not result["failed"] and not result["taken_out"]
    rows = store.list_equipment(conn, date(2026, 11, 23))
    assert next(r for r in rows if r["code"] == "FL-03")["checked_today"]
    assert not next(r for r in rows if r["code"] == "FL-03")["out_of_service"]


def test_non_critical_fail_passes_with_defect(conn):
    result = store.record_inspection(conn, "FL-03", "S-104", answers(conn, "FL-03", ["Horn"]), "horn weak", NOW)
    assert result["passed"] and result["failed"] == ["Horn works"] and not result["taken_out"]
    assert not store.get_equipment(conn, "FL-03")["out_of_service"]


def test_critical_fail_takes_equipment_out_of_service(conn):
    result = store.record_inspection(
        conn, "FL-03", "S-104", answers(conn, "FL-03", ["Brakes", "Horn"]), "brake pedal soft", NOW
    )
    assert not result["passed"] and result["taken_out"]
    equipment = store.get_equipment(conn, "FL-03")
    assert equipment["out_of_service"]
    assert equipment["out_of_service_reason"] == "Failed pre-use check: Brakes and parking brake hold"
    # A second failing check on equipment already out keeps the original reason and does not "take it out" again.
    again = store.record_inspection(conn, "FL-03", "S-105", answers(conn, "FL-03", ["Brakes"]), "still soft", NOW)
    assert again["taken_out"] is False
    assert store.get_equipment(conn, "FL-03")["out_of_service_since"] == "2026-11-23 07:30:00"


def test_check_needs_every_answer_and_notes_on_fail(conn):
    partial = answers(conn, "FL-03")
    partial.pop(next(iter(partial)))
    with pytest.raises(store.LogError, match="Missing: Brakes"):
        store.record_inspection(conn, "FL-03", "S-104", partial, "", NOW)
    with pytest.raises(store.LogError, match="notes"):
        store.record_inspection(conn, "FL-03", "S-104", answers(conn, "FL-03", ["Horn"]), "", NOW)
    with pytest.raises(store.LogError, match="Staff ID"):
        store.record_inspection(conn, "FL-03", "Jane Doe", answers(conn, "FL-03"), "", NOW)


def test_check_without_checklist(conn):
    store.add_equipment(conn, "WR-01", "Shrink wrapper", "wrapper", "", NOW)
    with pytest.raises(store.LogError, match="no checklist for kind 'wrapper'"):
        store.record_inspection(conn, "WR-01", "S-104", {}, "", NOW)


def test_return_to_service_needs_a_fix_record(conn):
    store.take_out_of_service(conn, "LD-01", "Bent step", NOW)
    with pytest.raises(store.LogError, match="already out"):
        store.take_out_of_service(conn, "LD-01", "again", NOW)
    with pytest.raises(store.LogError, match="What was fixed"):
        store.return_to_service(conn, "LD-01", "M-201", "", datetime(2026, 11, 24, 9, 0))
    store.return_to_service(conn, "LD-01", "M-201", "Replaced step 3", datetime(2026, 11, 24, 9, 0))
    assert not store.get_equipment(conn, "LD-01")["out_of_service"]
    events = store.history(conn, "LD-01")
    assert events[0]["summary"] == "repair, returned to service"
    with pytest.raises(store.LogError, match="not out of service"):
        store.return_to_service(conn, "LD-01", "M-201", "x", datetime(2026, 11, 24, 9, 0))


def test_due_list_and_late_entries(conn):
    today = date(2026, 11, 23)
    annual = store.add_task(conn, "FL-03", "Thorough examination", 365, "2025-11-20")
    monthly = store.add_task(conn, "LD-01", "Monthly ladder inspection", 30, "2026-11-10")
    never = store.add_task(conn, "LD-01", "Replace feet", 365)
    due = store.due_list(conn, today, within_days=7)
    assert [(d.task_id, d.days) for d in due] == [(never, None), (annual, -3)]
    assert due[0].never_done and due[0].due_on is None and due[0].overdue
    assert due[1].overdue and not due[1].never_done
    # A never-done task stays overdue and first however far ahead we look.
    later = store.due_list(conn, date(2027, 6, 1), within_days=0)
    assert later[0].task_id == never and later[0].overdue
    assert [d.task_id for d in store.due_list(conn, today, within_days=30)][-1] == monthly

    store.complete_task(conn, annual, "2026-11-23", "M-201", "passed", NOW)
    store.complete_task(conn, annual, "2026-11-01", "M-202", "late paper record", NOW)
    task = next(d for d in store.tasks_for(conn, "FL-03", today) if d.task_id == annual)
    assert task.due_on == date(2027, 11, 23)  # the late entry did not move it back


def test_task_validation(conn):
    with pytest.raises(store.LogError, match="whole number"):
        store.add_task(conn, "FL-03", "Service", "monthly")
    with pytest.raises(store.LogError, match="between 1 and 3660"):
        store.add_task(conn, "FL-03", "Service", 0)
    with pytest.raises(store.LogError, match="date like"):
        store.add_task(conn, "FL-03", "Service", 30, "23/11/2026")
    with pytest.raises(store.LogError, match="No maintenance task"):
        store.complete_task(conn, 999, "2026-11-23", "M-201", "", NOW)


def test_import_checklists_replaces_items_and_keeps_history(conn):
    store.record_inspection(conn, "LD-01", "S-104", answers(conn, "LD-01"), "", NOW)
    store.import_checklists(conn, {"checklists": {"ladder": {"title": "Ladder v2", "items": ["Only item"]}}})
    title, items = store.checklist_for(conn, "ladder")
    assert title == "Ladder v2" and [i["text"] for i in items] == ["Only item"]
    csv_text = store.inspections_csv(conn, date(2026, 11, 23), date(2026, 11, 23))
    assert "Rails and steps" in csv_text  # old answers keep their own text


@pytest.mark.parametrize(
    "data, message",
    [
        ({}, "no \\[checklists"),
        ({"checklists": {"x": {"title": "X", "items": []}}}, "non-empty list"),
        ({"checklists": {"x": {"items": ["a"]}}}, "title is required"),
        ({"checklists": {"x": {"title": "X", "items": [{"text": "a", "critical": "yes"}]}}}, "true or false"),
        ({"checklists": {"x": {"title": "X", "items": [3]}}}, "must be a string"),
    ],
)
def test_import_checklists_errors(conn, data, message):
    with pytest.raises(store.LogError, match=message):
        store.import_checklists(conn, data)


def test_csv_export_guards_formulas(conn):
    store.record_inspection(conn, "FL-03", "S-104", answers(conn, "FL-03", ["Horn"]), "=HYPERLINK(1)", NOW)
    store.record_inspection(conn, "LD-01", "S-104", answers(conn, "LD-01"), "", datetime(2026, 11, 25, 6, 0))
    body = store.inspections_csv(conn, date(2026, 11, 23), date(2026, 11, 23))
    lines = body.splitlines()
    assert lines[0].startswith("performed_at,code")
    assert len(lines) == 1 + 10  # ten forklift items, the ladder check is outside the range
    assert "'=HYPERLINK(1)" in body


def test_codes_are_case_insensitive(conn):
    with pytest.raises(store.LogError, match="FL-03 already exists"):
        store.add_equipment(conn, "fl-03", "Same truck", "forklift", "", NOW)
    assert store.get_equipment(conn, " fl-03 ")["code"] == "FL-03"


def test_repair_needs_a_new_check_and_history_order(conn):
    today = date(2026, 11, 23)
    store.record_inspection(conn, "FL-03", "S-104", answers(conn, "FL-03", ["Brakes"]), "soft", NOW)
    assert next(r for r in store.list_equipment(conn, today) if r["code"] == "FL-03")["checked_today"]
    store.return_to_service(conn, "FL-03", "M-201", "Bled brakes", datetime(2026, 11, 23, 9, 15))
    row = next(r for r in store.list_equipment(conn, today) if r["code"] == "FL-03")
    assert not row["checked_today"]  # the 07:30 check was before the repair
    store.record_inspection(conn, "FL-03", "S-104", answers(conn, "FL-03"), "", datetime(2026, 11, 23, 9, 20))
    assert next(r for r in store.list_equipment(conn, today) if r["code"] == "FL-03")["checked_today"]
    kinds = [e["type"] + ":" + e["summary"][:6] for e in store.history(conn, "FL-03")]
    assert kinds == ["check:passed", "maintenance:repair", "check:FAILED"]


def test_done_on_cannot_be_in_the_future(conn):
    task = store.add_task(conn, "FL-03", "Service", 90)
    with pytest.raises(store.LogError, match="future"):
        store.complete_task(conn, task, "2026-11-24", "M-201", "", NOW)
