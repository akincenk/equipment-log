from conftest import EXAMPLES

from equipment_log.cli import main


def test_cli_flow(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    assert main(["--db", db, "init"]) == 0
    assert "applied 0001_initial.sql" in capsys.readouterr().out
    assert main(["--db", db, "init"]) == 0
    assert "already up to date" in capsys.readouterr().out
    assert main(["--db", db, "checklists", str(EXAMPLES / "checklists.toml")]) == 0
    assert "forklift: 10 items" in capsys.readouterr().out
    assert main(["--db", db, "add", "FL-03", "Reach truck 3", "forklift"]) == 0
    assert main(["--db", db, "task", "FL-03", "Annual exam", "--every", "365", "--last-done", "2025-11-20"]) == 0
    capsys.readouterr()
    assert main(["--db", db, "due", "--today", "2026-11-23"]) == 2
    assert "overdue 3 d" in capsys.readouterr().out
    assert main(["--db", db, "due", "--today", "2026-11-01", "--days", "7"]) == 0
    assert "nothing due" in capsys.readouterr().out
    assert main(["--db", db, "task", "FL-03", "Load test", "--every", "365"]) == 0
    capsys.readouterr()
    assert main(["--db", db, "due", "--today", "2026-11-01", "--days", "7"]) == 2
    assert capsys.readouterr().out.splitlines() == ["never done  overdue        FL-03      Load test"]
    out = tmp_path / "checks.csv"
    assert main(["--db", db, "export", "-o", str(out)]) == 0
    assert out.read_text().startswith("performed_at")


def test_cli_errors(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    assert main(["--db", db, "add", "FL 03", "x", "forklift"]) == 1
    assert "Code must be" in capsys.readouterr().err
    bad = tmp_path / "bad.toml"
    bad.write_text("[checklists.x\n")
    assert main(["--db", db, "checklists", str(bad)]) == 1
    assert "bad.toml" in capsys.readouterr().err
    assert main(["--db", db, "checklists", str(tmp_path / "missing.toml")]) == 1
