"""Migrations on real Postgres: from an empty database, again, concurrently, and a failing one."""

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import psycopg
import pytest

from nock_api import migrate

FIRST = "0001_reflections_and_usage.sql"
EVERY = [FIRST, "0002_reports.sql"]


def tables(url: str) -> set[str]:
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    return {name for (name,) in rows}


def test_an_empty_database_gets_every_migration_once(empty_database_url: str) -> None:
    with psycopg.connect(empty_database_url, autocommit=True) as connection:
        assert migrate.migrate(connection, migrate.MIGRATIONS) == EVERY
        assert migrate.migrate(connection, migrate.MIGRATIONS) == []
        assert migrate.applied(connection) == set(EVERY)
    assert tables(empty_database_url) == {"schema_migrations", "reflections", "usage", "reports"}


def test_concurrent_runners_apply_each_migration_once(empty_database_url: str) -> None:
    applied: list[list[str]] = []

    def run() -> None:
        with psycopg.connect(empty_database_url, autocommit=True) as connection:
            applied.append(migrate.migrate(connection, migrate.MIGRATIONS))

    runners = [threading.Thread(target=run) for _ in range(3)]
    for runner in runners:
        runner.start()
    for runner in runners:
        runner.join(30)
    assert sorted(applied) == [[], [], EVERY]


def test_a_failing_migration_leaves_no_trace(empty_database_url: str, tmp_path: Path) -> None:
    shutil.copy(migrate.MIGRATIONS / FIRST, tmp_path / FIRST)
    (tmp_path / "0002_broken.sql").write_text("CREATE TABLE half (id int);\nSELECT nonsense;\n")
    with psycopg.connect(empty_database_url, autocommit=True) as connection:
        with pytest.raises(migrate.MigrationError, match=r"0002_broken\.sql"):
            migrate.migrate(connection, tmp_path)
        assert migrate.applied(connection) == {FIRST}
    assert "half" not in tables(empty_database_url)


def test_misnamed_or_missing_migrations_are_refused(tmp_path: Path) -> None:
    with pytest.raises(migrate.MigrationError, match="no migrations"):
        migrate.files(tmp_path)
    (tmp_path / "1_first.sql").write_text("")
    with pytest.raises(migrate.MigrationError, match=r"NNNN_name\.sql"):
        migrate.files(tmp_path)


def nock_api(*arguments: str, url: str | None) -> subprocess.CompletedProcess[str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in ("DATABASE_URL", "OTEL_EXPORTER_OTLP_HEADERS")
    }
    if url is not None:
        environment["DATABASE_URL"] = url
    return subprocess.run(
        [sys.executable, "-m", "nock_api", *arguments],
        capture_output=True,
        text=True,
        env=environment,
    )


def test_the_entry_point_migrates_the_database_its_environment_names(
    empty_database_url: str,
) -> None:
    first = nock_api("migrate", url=empty_database_url)
    assert first.returncode == 0, first.stderr
    assert first.stdout.splitlines() == [
        *(f"applied {name}" for name in EVERY),
        f"{len(EVERY)} migration(s) applied",
    ]
    assert nock_api("migrate", url=empty_database_url).stdout == "schema is up to date\n"
    missing = nock_api("migrate", url=None)
    assert missing.returncode == 2 and "DATABASE_URL is not set" in missing.stderr
