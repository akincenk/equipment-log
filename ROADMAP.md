# Roadmap

Planned work, about 29 hours in total. Each item has a GitHub issue with the label `roadmap`. Estimates include tests and docs.

## Core

1. **Login with staff accounts and roles** (about 4 h). Staff ID plus PIN, hashed with a slow hash from the standard library (`hashlib.scrypt`), signed session cookie, three roles: inspector (pre-use checks), maintenance (tasks, repairs, return to service), admin (equipment, checklists, accounts). Until then the app warns when it listens beyond localhost.
2. **Show never-done tasks as "never done"** (about 1 h). Today a task without a last-done date is "due today" every day, so it never becomes overdue and slides along the list. Show it as "never done" at the top of the due list and count it as overdue for `equipment-log due`. Found while running the demo site. **Done:** listed first as "never done" on the CLI, start page and equipment page, and `due` exits 2 for it.
3. **Edit and retire equipment** (about 2 h). Change name, kind and location; retire equipment that has left the site so it disappears from the daily lists but keeps its history and stays in exports. No hard delete.
4. **Open defects list** (about 3 h). Non-critical fails (horn quiet, label unreadable) become defects with open/closed status, shown on the start page and on the equipment page until maintenance closes them with a note. A defect that is still open after N days is highlighted.
5. **Checklist editor in the web app** (about 3 h). Add, reorder, retire and mark items critical from the admin pages, with a version number per checklist that is saved with every check, so an audit shows which version was used.

## Scheduling

6. **Usage-based intervals** (about 3 h). Record hour-meter readings during the pre-use check (optional field per kind) and allow tasks like "every 250 hours" next to "every 90 days", whichever comes first.
7. **Checks per shift** (about 2 h). Configurable shift start times (for example 06:00, 14:00, 22:00) so "checked today" becomes "checked this shift" on sites that run more than one shift.
8. **Due list as JSON and as a calendar feed** (about 2 h). `equipment-log due --format json` for scripts, and a read-only `.ics` feed of due tasks that a shared calendar can subscribe to.

## Labels and data

9. **QR label per equipment** (about 2 h). A printable page of QR codes that open the pre-use check for each piece of equipment, sized for common label sheets; the codes use the same equipment code that is painted on the truck.
10. **Import equipment from CSV** (about 1.5 h). `equipment-log import equipment.csv` with a dry run that lists what would be added or changed and rejects duplicate codes.

## Running it

11. **Backup command and container image** (about 2 h). `equipment-log backup FILE` using SQLite's online backup API, a Dockerfile with a non-root user and a volume for the database, and docs for a small office server.
12. **Browser test in CI** (about 2 h). A Playwright smoke test that runs a check on a phone-sized viewport, fails a critical item, records the repair and confirms the start page.
13. **Accessibility and phone layout pass** (about 1.5 h). Run axe on every page, fix what it finds, make radio buttons large enough for gloved hands, and check keyboard-only use.
