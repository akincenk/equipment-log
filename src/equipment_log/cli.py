"""Command line: set up the database, load checklists, list what is due, export, and run the web app."""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from datetime import date, datetime, timedelta

from . import __version__, store
from .db import connect, migrate, open_db

DEFAULT_DB = "equipment-log.db"


def _day(value: str) -> date:
    try:
        return store.parse_day(value, "date")
    except store.LogError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="equipment-log", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--db",
        default=os.environ.get("EQUIPMENT_LOG_DB", DEFAULT_DB),
        help=f"SQLite file (default: $EQUIPMENT_LOG_DB or {DEFAULT_DB})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the database or apply new migrations")

    p = sub.add_parser("checklists", help="load checklists from a TOML file")
    p.add_argument("file")

    p = sub.add_parser("add", help="add a piece of equipment")
    p.add_argument("code")
    p.add_argument("name")
    p.add_argument("kind")
    p.add_argument("--location", default="")

    p = sub.add_parser("task", help="add a scheduled maintenance task")
    p.add_argument("code")
    p.add_argument("title")
    p.add_argument("--every", type=int, required=True, metavar="DAYS")
    p.add_argument("--last-done", default="", metavar="YYYY-MM-DD")

    p = sub.add_parser("due", help="list maintenance due soon; exit 2 when something is overdue")
    p.add_argument("--days", type=int, default=7, help="look ahead this many days (default 7)")
    p.add_argument("--today", type=_day, default=None, help=argparse.SUPPRESS)

    p = sub.add_parser("export", help="write pre-use checks as CSV")
    p.add_argument("--since", type=_day, default=None, help="first day (default: 30 days ago)")
    p.add_argument("--until", type=_day, default=None, help="last day (default: today)")
    p.add_argument("-o", "--output", default="-", help="file to write (default: stdout)")

    p = sub.add_parser("serve", help="run the web app")
    p.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1, this machine only)")
    p.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except store.LogError as exc:
        print(f"equipment-log: {exc}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    if args.command == "init":
        conn = connect(args.db)
        applied = migrate(conn)
        print(f"{args.db}: " + (f"applied {', '.join(applied)}" if applied else "already up to date"))
        return 0

    if args.command == "serve":
        import uvicorn

        from .web import create_app

        if args.host not in ("127.0.0.1", "localhost", "::1"):
            print(
                "equipment-log: warning: there is no login yet; anyone who can reach "
                f"{args.host}:{args.port} can change the log.",
                file=sys.stderr,
            )
        uvicorn.run(create_app(args.db), host=args.host, port=args.port)
        return 0

    conn = open_db(args.db)
    if args.command == "checklists":
        try:
            with open(args.file, "rb") as fh:
                data = tomllib.load(fh)
        except OSError as exc:
            raise store.LogError(f"cannot read {args.file}: {exc.strerror}") from None
        except tomllib.TOMLDecodeError as exc:
            raise store.LogError(f"{args.file}: {exc}") from None
        for kind in store.import_checklists(conn, data):
            _, items = store.checklist_for(conn, kind)
            print(f"{kind}: {len(items)} items")
        return 0

    if args.command == "add":
        store.add_equipment(conn, args.code, args.name, args.kind, args.location, datetime.now())
        print(f"added {args.code}")
        return 0

    if args.command == "task":
        store.add_task(conn, args.code, args.title, args.every, args.last_done)
        print(f"{args.code}: task added")
        return 0

    if args.command == "due":
        today = args.today or date.today()
        due = store.due_list(conn, today, within_days=args.days)
        for d in due:
            when = f"overdue {-d.days} d" if d.overdue else ("today" if d.days == 0 else f"in {d.days} d")
            print(f"{d.due_on.isoformat()}  {when:<14} {d.code:<10} {d.title}")
        if not due:
            print(f"nothing due in the next {args.days} days")
        return 2 if any(d.overdue for d in due) else 0

    if args.command == "export":
        today = date.today()
        body = store.inspections_csv(conn, args.since or today - timedelta(days=30), args.until or today)
        if args.output == "-":
            sys.stdout.write(body)
        else:
            with open(args.output, "w", encoding="utf-8", newline="") as fh:
                fh.write(body)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
