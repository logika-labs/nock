"""`nock-api serve` and `nock-api migrate`: the entry point, the only place that reads the environment
and the clock.

`DATABASE_URL` names the database; when `OTEL_EXPORTER_OTLP_HEADERS` holds an SDK key, the server sends
its own spans to Logika, else it runs untraced. On the box both come from `/etc/nock-api/nock-api.env`.
"""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import uvicorn

from nock_api import app, migrate, telemetry
from nock_api.limit import Limit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nock-api", description=(__doc__ or "").split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="answer HTTP until stopped")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8610)
    migrating = commands.add_parser("migrate", help="apply the pending schema migrations")
    migrating.add_argument(
        "--directory", type=Path, default=migrate.MIGRATIONS, help="defaults to the repository's"
    )
    arguments = parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("nock-api: DATABASE_URL is not set", file=sys.stderr)
        return 2
    if os.environ.get("OTEL_EXPORTER_OTLP_HEADERS"):
        telemetry.start()
    if arguments.command == "migrate":
        with psycopg.connect(database_url, autocommit=True) as connection:
            try:
                names = migrate.migrate(connection, arguments.directory)
            except migrate.MigrationError as error:
                print(f"migration failed: {error}", file=sys.stderr)
                return 1
        for name in names:
            print(f"applied {name}")
        print(f"{len(names)} migration(s) applied" if names else "schema is up to date")
        return 0
    uvicorn.run(
        app.create(database_url, lambda: datetime.now(UTC), Limit()),
        host=arguments.host,
        port=arguments.port,
        # No access log: the server keeps nothing about its senders.
        access_log=False,
        # The sender's address is read from Caddy's X-Forwarded-For by `app.sender` itself.
        proxy_headers=False,
        server_header=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
