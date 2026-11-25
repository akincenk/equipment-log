from datetime import datetime

import pytest
from conftest import EXAMPLES
from fastapi.testclient import TestClient

from equipment_log import store
from equipment_log.web import create_app

NOW = datetime(2026, 11, 23, 7, 30)


@pytest.fixture
def client(tmp_path):
    import tomllib

    app = create_app(tmp_path / "web.db", clock=lambda: NOW)
    with open(EXAMPLES / "checklists.toml", "rb") as fh:
        store.import_checklists(app.state.conn, tomllib.load(fh))
    with TestClient(app) as client:
        yield client


def add(client, code="FL-03", kind="forklift"):
    return client.post("/equipment", data={"code": code, "name": "Reach truck 3", "kind": kind, "location": "Dock B"})


def test_add_equipment_and_dashboard(client):
    r = add(client)
    assert r.status_code == 200 and "Added FL-03." in r.text
    r = client.get("/")
    assert "Check FL-03" in r.text and "Nothing is out of service." in r.text


def test_add_equipment_error_keeps_form(client):
    add(client)
    r = add(client)
    assert r.status_code == 400 and "already exists" in r.text and 'value="Reach truck 3"' in r.text


def test_search_returns_rows_only_for_htmx(client):
    add(client)
    add(client, "LD-01", "ladder")
    r = client.get("/equipment", params={"q": "ladder"}, headers={"HX-Request": "true"})
    assert "<html" not in r.text and "LD-01" in r.text and "FL-03" not in r.text


def test_failed_critical_check_flags_and_return_to_service(client):
    add(client)
    conn = client.app.state.conn
    _, items = store.checklist_for(conn, "forklift")
    form = {f"item-{i['id']}": "ok" for i in items}
    form[f"item-{items[0]['id']}"] = "fail"
    form.update(inspector="S-104", notes="brake pedal soft")
    r = client.post("/equipment/FL-03/check", data=form)
    assert "OUT OF SERVICE: do not use it" in r.text
    assert "Failed pre-use check: Brakes" in client.get("/").text

    r = client.post("/equipment/FL-03/return", data={"done_by": "M-201", "notes": ""})
    assert r.status_code == 400 and "What was fixed is required" in r.text
    r = client.post("/equipment/FL-03/return", data={"done_by": "M-201", "notes": "Bled brakes"})
    assert "back in service" in r.text
    assert r.text.index("returned to service") < r.text.index("check: FAILED")  # same second: repair listed first
    assert "Check FL-03" in client.get("/").text  # needs a new pre-use check after the repair


def test_check_form_errors_keep_answers(client):
    add(client)
    conn = client.app.state.conn
    _, items = store.checklist_for(conn, "forklift")
    form = {f"item-{items[0]['id']}": "na", "inspector": "S-104"}
    r = client.post("/equipment/FL-03/check", data=form)
    assert r.status_code == 400 and "Answer every item" in r.text
    assert 'value="na" required checked' in r.text


def test_task_done_htmx_returns_row(client):
    add(client)
    r = client.post("/equipment/FL-03/tasks", data={"title": "Annual exam", "interval_days": "365", "last_done": ""})
    assert "Task added." in r.text
    assert 'class="overdue"' in r.text and "never done" in r.text
    page = client.get("/").text
    assert "never done" in page and "Annual exam" in page
    task = store.tasks_for(client.app.state.conn, "FL-03", NOW.date())[0]
    r = client.post(
        f"/tasks/{task.task_id}/done",
        data={"code": "FL-03", "done_on": "2026-11-23", "done_by": "M-201", "notes": ""},
        headers={"HX-Request": "true"},
    )
    assert r.text.lstrip().startswith(f'<tr id="task-{task.task_id}"') and "2027-11-23" in r.text
    r = client.post(
        f"/tasks/{task.task_id}/done", data={"code": "FL-03", "done_by": "bad id!"}, headers={"HX-Request": "true"}
    )
    assert r.status_code == 200 and 'role="alert">Staff ID' in r.text and r.text.lstrip().startswith("<tr")


def test_cross_site_post_is_refused(client):
    r = client.post("/equipment", data={"code": "X-1"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/equipment", data={"code": "X-1"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_output_is_escaped(client):
    client.post("/equipment", data={"code": "SC-1", "name": "<script>alert(1)</script>", "kind": "scanner"})
    r = client.get("/equipment/SC-1")
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text


def test_unknown_equipment_and_export(client):
    assert client.get("/equipment/NOPE").status_code == 404
    r = client.get("/export.csv", params={"since": "2026-11-01"})
    assert r.headers["content-type"].startswith("text/csv") and r.text.startswith("performed_at")
    assert client.get("/export.csv", params={"since": "yesterday"}).status_code == 400
