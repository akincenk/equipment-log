"""FastAPI app: server-rendered pages, HTMX for the small in-page updates."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import store
from .db import open_db

HERE = Path(__file__).parent


def _same_origin(request: Request) -> bool:
    """Reject cross-site form posts (CSRF). Clients that send neither header, like curl, are allowed."""
    origin = request.headers.get("origin")
    if origin:
        return urlsplit(origin).netloc == request.headers.get("host")
    site = request.headers.get("sec-fetch-site")
    if site:
        return site in ("same-origin", "none")
    return True


def create_app(db_path: str | Path, clock: Callable[[], datetime] = datetime.now) -> FastAPI:
    app = FastAPI(title="equipment-log", docs_url=None, redoc_url=None, openapi_url=None)
    conn = open_db(db_path)
    templates = Jinja2Templates(directory=HERE / "templates")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def today() -> date:
        return clock().date()

    def page(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
        context.setdefault("message", request.query_params.get("msg", ""))
        context.setdefault("error", "")
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    def back(path: str, message: str) -> RedirectResponse:
        return RedirectResponse(f"{path}?msg={quote(message)}", status_code=303)

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS") and not _same_origin(request):
            return PlainTextResponse("Cross-site request refused.", status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        day = today()
        equipment = store.list_equipment(conn, day)
        return page(
            request,
            "dashboard.html",
            out=[e for e in equipment if e["out_of_service"]],
            unchecked=[e for e in equipment if not e["out_of_service"] and not e["checked_today"]],
            due=store.due_list(conn, day, within_days=14),
            today=day,
        )

    @app.get("/equipment", response_class=HTMLResponse)
    def equipment_list(request: Request, q: str = ""):
        rows = store.list_equipment(conn, today(), q)
        name = "_equipment_rows.html" if request.headers.get("hx-request") else "equipment.html"
        return page(request, name, rows=rows, q=q)

    @app.post("/equipment")
    async def equipment_add(request: Request):
        form = await request.form()
        try:
            store.add_equipment(
                conn,
                form.get("code", ""),
                form.get("name", ""),
                form.get("kind", ""),
                form.get("location", ""),
                clock(),
            )
        except store.LogError as exc:
            rows = store.list_equipment(conn, today())
            return page(request, "equipment.html", 400, rows=rows, q="", error=str(exc), form=form)
        code = form.get("code", "").strip().upper()
        return back(f"/equipment/{quote(code)}", f"Added {code}.")

    def detail(request: Request, code: str, status_code: int = 200, error: str = "") -> HTMLResponse:
        equipment = store.get_equipment(conn, code)
        _, items = store.checklist_for(conn, equipment["kind"])
        return page(
            request,
            "detail.html",
            status_code,
            e=equipment,
            tasks=store.tasks_for(conn, code, today()),
            events=store.history(conn, code),
            has_checklist=bool(items),
            today=today(),
            error=error,
        )

    @app.get("/equipment/{code}", response_class=HTMLResponse)
    def equipment_detail(request: Request, code: str):
        try:
            return detail(request, code)
        except store.LogError as exc:
            return PlainTextResponse(str(exc), status_code=404)

    @app.get("/equipment/{code}/check", response_class=HTMLResponse)
    def check_form(request: Request, code: str):
        try:
            equipment = store.get_equipment(conn, code)
        except store.LogError as exc:
            return PlainTextResponse(str(exc), status_code=404)
        title, items = store.checklist_for(conn, equipment["kind"])
        return page(request, "check.html", e=equipment, title=title, items=items, answers={}, form={})

    @app.post("/equipment/{code}/check")
    async def check_save(request: Request, code: str):
        form = await request.form()
        try:
            equipment = store.get_equipment(conn, code)
        except store.LogError as exc:
            return PlainTextResponse(str(exc), status_code=404)
        answers = {}
        for key, value in form.items():
            if key.startswith("item-") and key[5:].isdigit():
                answers[int(key[5:])] = value
        try:
            result = store.record_inspection(
                conn, code, form.get("inspector", ""), answers, form.get("notes", ""), clock()
            )
        except store.LogError as exc:
            title, items = store.checklist_for(conn, equipment["kind"])
            return page(
                request, "check.html", 400, e=equipment, title=title, items=items, answers=answers, form=form,
                error=str(exc),
            )  # fmt: skip
        if result["taken_out"]:
            message = f"Check saved. {code} is now OUT OF SERVICE: do not use it."
        elif not result["passed"]:
            message = "Check saved. Critical items failed; it was already out of service."
        elif result["failed"]:
            message = "Check passed with defects. Report them to maintenance."
        else:
            message = "Check passed."
        return back(f"/equipment/{quote(code)}", message)

    @app.post("/equipment/{code}/out")
    async def out_of_service(request: Request, code: str):
        form = await request.form()
        try:
            store.take_out_of_service(conn, code, form.get("reason", ""), clock())
        except store.LogError as exc:
            return _form_error(request, code, exc)
        return back(f"/equipment/{quote(code)}", f"{code} taken out of service.")

    @app.post("/equipment/{code}/return")
    async def back_in_service(request: Request, code: str):
        form = await request.form()
        try:
            store.return_to_service(conn, code, form.get("done_by", ""), form.get("notes", ""), clock())
        except store.LogError as exc:
            return _form_error(request, code, exc)
        return back(f"/equipment/{quote(code)}", f"{code} is back in service.")

    @app.post("/equipment/{code}/tasks")
    async def task_add(request: Request, code: str):
        form = await request.form()
        try:
            store.add_task(conn, code, form.get("title", ""), form.get("interval_days", ""), form.get("last_done", ""))
        except store.LogError as exc:
            return _form_error(request, code, exc)
        return back(f"/equipment/{quote(code)}", "Task added.")

    @app.post("/tasks/{task_id}/done")
    async def task_done(request: Request, task_id: int):
        form = await request.form()
        code = form.get("code", "")
        try:
            store.complete_task(
                conn,
                task_id,
                form.get("done_on", "") or today(),
                form.get("done_by", ""),
                form.get("notes", ""),
                clock(),
            )
        except store.LogError as exc:
            if not request.headers.get("hx-request"):
                return _form_error(request, code, exc)
            error = str(exc)
        else:
            if not request.headers.get("hx-request"):
                return back(f"/equipment/{quote(code)}", "Task recorded.")
            error = ""
        # htmx does not swap 4xx responses by default, so the row comes back with 200 and the message inside it.
        task = next((t for t in store.tasks_for(conn, code, today()) if t.task_id == task_id), None)
        if task is None:
            return PlainTextResponse("No such task for this equipment.", status_code=404)
        return page(request, "_task_row.html", t=task, code=code, today=today(), error=error)

    def _form_error(request: Request, code: str, exc: Exception) -> Response:
        try:
            return detail(request, code, 400, error=str(exc))
        except store.LogError:
            return PlainTextResponse(str(exc), status_code=404)

    @app.get("/export.csv")
    def export(since: str = "", until: str = ""):
        day = today()
        try:
            start = store.parse_day(since, "since") if since else day - timedelta(days=30)
            end = store.parse_day(until, "until") if until else day
        except store.LogError as exc:
            return PlainTextResponse(str(exc), status_code=400)
        body = store.inspections_csv(conn, start, end)
        name = f"inspections-{start}-{end}.csv"
        return Response(body, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    app.state.conn = conn
    return app
