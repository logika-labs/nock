"""Forward-only schema migrations: `server/migrations/NNNN_name.sql`, applied in name order.

Each file runs in its own transaction together with its `schema_migrations` row, so a failing file leaves
no trace and a re-run applies exactly what is missing. An advisory lock serialises concurrent runners.
"""

import re
from pathlib import Path

from psycopg import Connection

from nock_api.telemetry import tracer

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

NAME = re.compile(r"\d{4}_[a-z0-9_]+\.sql")
LOCK = 0x6E6F636B  # "nock"


class MigrationError(Exception):
    pass


def files(directory: Path) -> list[Path]:
    found = sorted(directory.glob("*.sql"))
    # An installed wheel has no migrations beside it: finding nothing must fail, not pass as up to date.
    if not found:
        raise MigrationError(f"no migrations in {directory}")
    misnamed = [path.name for path in found if not NAME.fullmatch(path.name)]
    if misnamed:
        raise MigrationError(f"migrations are named NNNN_name.sql: {', '.join(misnamed)}")
    return found


def applied(connection: Connection) -> set[str]:
    row = connection.execute("SELECT to_regclass('schema_migrations') IS NOT NULL").fetchone()
    if row is None or not row[0]:
        return set()
    return {name for (name,) in connection.execute("SELECT name FROM schema_migrations")}


def migrate(connection: Connection, directory: Path) -> list[str]:
    """Apply every pending migration on an autocommit connection; the names applied, in order."""
    pending = files(directory)
    with tracer.start_as_current_span("migrate"):
        connection.execute("SELECT pg_advisory_lock(%s)", [LOCK])
        try:
            done = applied(connection)
            names: list[str] = []
            for path in pending:
                if path.name in done:
                    continue
                try:
                    with connection.transaction():
                        connection.execute(path.read_bytes())
                        connection.execute(
                            "INSERT INTO schema_migrations (name) VALUES (%s)", [path.name]
                        )
                except Exception as error:
                    raise MigrationError(f"{path.name}: {error}") from error
                tracer.start_span("migrate.applied", attributes={"migration": path.name}).end()
                names.append(path.name)
            return names
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", [LOCK])
