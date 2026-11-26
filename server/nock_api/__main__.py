"""`nock-api serve`, `nock-api migrate` and `nock-api reports`: the entry point, the only place that
reads the environment and the clock.

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
    listing = commands.add_parser(
        "reports", help="print the latest reports people sent, newest first"
    )
    listing.add_argument("--limit", type=int, default=20, help="how many (default: 20)")
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
    if arguments.command == "reports":
        with psycopg.connect(database_url) as connection:
            print(latest_reports(connection, arguments.limit))
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


def latest_reports(connection: psycopg.Connection, limit: int) -> str:
    """The latest `limit` reports, newest first: each one's id, when it arrived, nock's version and the
    platform, then its text, indented."""
    rows = connection.execute(
        "SELECT id, received, nock, platform, text FROM reports ORDER BY id DESC LIMIT %s",
        [limit],
    ).fetchall()
    if not rows:
        return "no reports yet"
    entries = []
    for identity, received, nock, platform, text in rows:
        moment = received.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        body = "\n".join(f"    {line}" for line in text.splitlines())
        entries.append(f"#{identity}  {moment}  nock {nock} on {platform}\n{body}")
    return "\n\n".join(entries)


if __name__ == "__main__":
    sys.exit(main())
