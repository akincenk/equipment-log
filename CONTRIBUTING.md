# Contributing

Thanks for looking at equipment-log. Issues and pull requests are welcome.

## Set up

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
```

## Before you open a pull request

```sh
ruff check .
ruff format --check .
pytest -q
gitleaks dir .
```

CI runs the same checks on Python 3.11 and 3.14, plus a gitleaks scan of the history and zizmor on the workflows.

## Guidelines

- One change per pull request, with tests. Bug fixes start with a test that fails.
- Database changes go in a new numbered file in `src/equipment_log/migrations/`. Never edit a migration that has been released.
- All database access goes through `store.py`; the web and CLI layers only parse input and render output.
- Sample data must be made up. Use staff IDs like `S-104`, never real names, phone numbers or company data.
- The planned work is in [ROADMAP.md](ROADMAP.md); each item has a GitHub issue. Comment on the issue before starting a large item.
