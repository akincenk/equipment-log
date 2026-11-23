# equipment-log

[![CI](https://github.com/akincenk/equipment-log/actions/workflows/ci.yml/badge.svg)](https://github.com/akincenk/equipment-log/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/akincenk/equipment-log/badge)](https://scorecard.dev/viewer/?uri=github.com/akincenk/equipment-log)

A small web app for the equipment a team shares: forklifts, pallet jacks, ladders, handheld scanners. Staff do a pre-use check on a phone before they use a piece of equipment, maintenance tasks come due on a schedule, and anything that fails a critical check is flagged out of service until someone records the repair.

## Who it is for

Supervisors and maintenance leads in small warehouses, stockrooms, workshops and stores. A common way to track this is a paper checklist on a clipboard next to the charger and a spreadsheet of service dates, which makes it hard to answer three questions at the start of a shift: what is out of service and why, what maintenance is overdue, and what has not been checked today. The start page of equipment-log answers exactly those three.

## What it does

- **Pre-use checks** from a checklist per kind of equipment (forklift, ladder, ...). Every item is answered OK, Fail or Not applicable, with a staff ID.
- **Critical items.** A failed critical item (brakes, forks, ladder rails) takes the equipment out of service at once. A failed non-critical item (horn, label) is saved as a defect and the check still passes.
- **Out of service until fixed.** Equipment goes back in service only with a maintenance record that says what was fixed and by whom. After that it needs a new pre-use check before it counts as checked today.
- **Scheduled maintenance** with a fixed interval in days (monthly ladder inspection, annual thorough examination). A late paper record for an older date never moves the next due date backwards.
- **History** per piece of equipment, and a **CSV export** of every answered item for audits (cells that a spreadsheet would run as formulas are prefixed with `'`).
- A command line for setup and for a cron job: `equipment-log due` exits with code 2 when something is overdue.

Staff are identified by a short staff ID such as `S-104`, not by name. There is no login yet (see [ROADMAP.md](ROADMAP.md)); by default the app only listens on 127.0.0.1.

The checklists in `examples/checklists.toml` are samples written for this project. They are not a regulator's form. Check your own local rules and the manufacturer's manual for what your checks and examinations must cover.

## Stack

- Python 3.11+, [FastAPI](https://fastapi.tiangolo.com/) with server-rendered [Jinja2](https://jinja.palletsprojects.com/) templates
- [htmx](https://htmx.org/) 2.0.11 for the live search and for recording a task without a page reload (vendored in `src/equipment_log/static/`, 0BSD licence; the file matches the npm package integrity hash)
- SQLite through the standard library `sqlite3`, with numbered SQL migrations in `src/equipment_log/migrations/` tracked by `PRAGMA user_version`
- pytest (store, web and CLI tests), ruff, GitHub Actions

## Run it

```sh
git clone https://github.com/akincenk/equipment-log.git
cd equipment-log
python3 -m venv .venv && . .venv/bin/activate
pip install -e .

equipment-log --db site.db init
equipment-log --db site.db checklists examples/checklists.toml
equipment-log --db site.db add FL-03 "Reach truck 3" forklift --location "Dock B"
equipment-log --db site.db task FL-03 "Thorough examination" --every 365 --last-done 2026-06-15
equipment-log --db site.db serve
```

Then open http://127.0.0.1:8000. `--db` can also be set with `EQUIPMENT_LOG_DB`.

For a fuller made-up site with 14 pieces of equipment and their maintenance plan:

```sh
sh examples/demo-warehouse.sh demo.db
equipment-log --db demo.db due --days 14
equipment-log --db demo.db serve
```

### Commands

| Command | What it does |
| --- | --- |
| `init` | create the database or apply new migrations |
| `checklists FILE.toml` | load or replace checklists |
| `add CODE NAME KIND [--location]` | add equipment (codes are stored in upper case) |
| `task CODE TITLE --every DAYS [--last-done DATE]` | add a scheduled maintenance task |
| `due [--days 7]` | list tasks due soon; exit code 2 if anything is overdue |
| `export [--since] [--until] [-o FILE]` | pre-use checks as CSV (default: last 30 days) |
| `serve [--host] [--port]` | run the web app (default 127.0.0.1:8000) |

### Checklist file

```toml
[checklists.ladder]
title = "Ladder / rolling stair check"
items = [
  { text = "Rails and steps: no cracks, bends or loose rivets", critical = true },
  "Label with load rating readable",
]
```

Loading a file again replaces the items of each kind in it. Past checks keep the item text they were answered with.

## Security notes

- No login yet. Keep the default `--host 127.0.0.1`, or put it behind something that authenticates, until the login item on the roadmap is done. `serve` prints a warning when it listens on another address.
- Cross-site form posts are refused (Origin / Sec-Fetch-Site check), templates escape all output, and every SQL statement uses parameters.

## Tests

```sh
pip install -e '.[dev]'
ruff check . && ruff format --check . && pytest -q
```

## Similar projects

- [Atlas CMMS](https://github.com/Grashjs/cmms) is a full maintenance management system (work orders, purchase orders, users, mobile app) built with Java and React. equipment-log is much smaller: one process, one SQLite file, focused on pre-use checks and the out-of-service rule.
- [Snipe-IT](https://github.com/grokability/snipe-it) and [Shelf](https://github.com/Shelf-nu/shelf.nu) track IT assets and who has them, not pre-use inspections.

## Licence

MIT, see [LICENSE](LICENSE).
