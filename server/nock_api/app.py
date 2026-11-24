"""The ASGI app: `GET /health`, `POST /reflections`, `POST /usage`, `POST /reports`, `POST /docs` and
`GET /docs/{cli}` (nock's hosted docs, `nock_api.docs`), and the edge every request passes.

Every `POST` but `/docs` answers `201` with `{"id": N}` (`/docs`: the bundle's `min_cli` and `version`), or `{"error": "…"}` with `400` naming what is wrong, `411`
without a `Content-Length`, `413` when the body is too large (refused unread), `429` beyond the rate limit
(with `Retry-After`); anything else is `404` (`501` for a method other than `GET` and `POST`). Rows are
kept with the moment they arrived, `now()`, and nothing about the sender.
"""

import json
import math
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, LiteralString

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from nock_api import docs, rules
from nock_api.limit import BURST, Limit
from nock_api.telemetry import tracer

# The pool's bounds: a handful of posts a minute arrive, each one INSERT.
CONNECTIONS = (1, 4)


class Edge:
    """What happens before routing. A method other than `GET` and `POST` is not implemented; every `POST`,
    to any path, spends its sender's rate limit first, and its trailing slashes are dropped; a query string
    names nothing."""

    def __init__(self, app: ASGIApp, limit: Limit, now: Callable[[], datetime]) -> None:
        self.app = app
        self.limit = limit
        self.now = now

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope["method"]
        if method not in ("GET", "POST"):
            answer = JSONResponse({"error": f"Unsupported method ('{method}')"}, 501)
            await answer(scope, receive, send)
            return
        if method == "POST":
            wait = self.limit.take(sender(scope), self.now().timestamp())
            if wait:
                retry = math.ceil(wait)
                tracer.start_span("limited", attributes={"retry_after": retry}).end()
                answer = JSONResponse(
                    {"error": f"at most {BURST} at once and 6 a minute; try again later"},
                    429,
                    headers={"Retry-After": str(retry)},
                )
                await answer(scope, receive, send)
                return
            scope = {**scope, "path": scope["path"].rstrip("/")}
        if scope["query_string"]:
            await JSONResponse({"error": "nothing here"}, 404)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def sender(scope: Scope) -> str:
    """The sender's address: Caddy's, on this box, says whom it forwards for. Held only by the limit."""
    peer = scope["client"][0] if scope.get("client") else ""
    if peer != "127.0.0.1":
        return peer
    for name, value in scope["headers"]:
        if name == b"x-forwarded-for":
            forwarded = value.decode("latin-1").split(",")[0].strip()
            return forwarded or peer
    return peer


class Refusal(Exception):
    """A refused `POST`: its status, the error its body says, and why in a word, for the span."""

    def __init__(self, status: int, error: str, reason: str) -> None:
        super().__init__(error)
        self.status = status
        self.reason = reason

    def attributes(self) -> dict[str, int | str]:
        """The refused outcome's: an expected one, so its operation closes without an error."""
        return {"http_status": self.status, "reason": self.reason}

    def answer(self) -> JSONResponse:
        return JSONResponse({"error": str(self)}, self.status)


async def read[T](request: Request, path: str, rule: Callable[[Any], T]) -> T:
    """What a `POST` sent, held to `rule`, or a `Refusal`: no length, too long (refused unread), not
    JSON, not what the endpoint keeps."""
    length = request.headers.get("content-length")
    if length is None:
        raise Refusal(411, "Content-Length is required", "no_length")
    try:
        announced = int(length)
    except ValueError:
        announced = -1
    if announced < 0:
        raise Refusal(400, "Content-Length is a whole number of at least 0", "no_length")
    largest = docs.LARGEST if path == "/docs" else rules.LARGEST[path]
    if announced > largest:
        raise Refusal(413, f"at most {largest} bytes", "too_large")
    try:
        sent = json.loads(await request.body())
    except (ValueError, RecursionError) as error:
        raise Refusal(400, str(error), "not_json") from error
    try:
        return rule(sent)
    except rules.Refused as error:
        raise Refusal(400, str(error), error.reason) from error
    except (ValueError, TypeError) as error:
        raise Refusal(400, str(error), "value") from error


def create(
    database_url: str, now: Callable[[], datetime], limit: Limit, docs_key: str = docs.PUBLIC_KEY
) -> ASGIApp:
    """The app over the database at `database_url`, its rows received at `now()`, its posts limited by
    `limit`, the docs it keeps signed with `docs_key` (base64). The connection pool opens and closes with
    the app's lifespan."""
    public = docs.key(docs_key)
    pool = AsyncConnectionPool[AsyncConnection](
        database_url,
        min_size=CONNECTIONS[0],
        max_size=CONNECTIONS[1],
        kwargs={"autocommit": True},
        check=AsyncConnectionPool.check_connection,
        open=False,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await pool.open(wait=True)
        try:
            yield
        finally:
            await pool.close()

    app = FastAPI(
        lifespan=lifespan,
        redirect_slashes=False,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    async def keep(statement: LiteralString, values: tuple[Any, ...]) -> int:
        async with pool.connection() as connection:
            cursor = await connection.execute(statement, (now(), *values))
            row = await cursor.fetchone()
        assert row is not None
        return int(row[0])

    @app.exception_handler(HTTPException)
    async def nothing_here(request: Request, error: HTTPException) -> JSONResponse:
        if error.status_code in (404, 405):
            return JSONResponse({"error": "nothing here"}, 404)
        return JSONResponse({"error": error.detail}, error.status_code, headers=error.headers)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/reflections")
    async def reflections(request: Request) -> JSONResponse:
        with tracer.start_as_current_span("reflection", attributes=size(request)):
            try:
                summary, round = await read(request, "/reflections", rules.reflection)
            except Refusal as refusal:
                tracer.start_span("reflection.refused", attributes=refusal.attributes()).end()
                return refusal.answer()
            identity = await keep(
                "INSERT INTO reflections (received, round, summary) VALUES (%s, %s, %s)"
                " RETURNING id",
                (round, summary),
            )
            tracer.start_span(
                "reflection.kept",
                attributes={
                    "row_id": identity,
                    "summary_chars": len(summary),
                    "dated": round is not None,
                },
            ).end()
        return JSONResponse({"id": identity}, 201)

    @app.post("/usage")
    async def usage(request: Request) -> JSONResponse:
        with tracer.start_as_current_span("usage", attributes=size(request)):
            try:
                report = await read(request, "/usage", rules.report)
            except Refusal as refusal:
                tracer.start_span("usage.refused", attributes=refusal.attributes()).end()
                return refusal.answer()
            identity = await keep(
                "INSERT INTO usage (received, project, schema, report) VALUES (%s, %s, %s, %s)"
                " RETURNING id",
                (report["project"], report["schema"], Jsonb(report)),
            )
            tracer.start_span(
                "usage.kept",
                attributes={
                    "row_id": identity,
                    "schema": report["schema"],
                    "commands": len(report["commands"]),
                    "metrics": len(report["metrics"]),
                },
            ).end()
        return JSONResponse({"id": identity}, 201)

    @app.post("/reports")
    async def reports(request: Request) -> JSONResponse:
        with tracer.start_as_current_span("report", attributes=size(request)):
            try:
                text, nock, platform = await read(request, "/reports", rules.written)
            except Refusal as refusal:
                tracer.start_span("report.refused", attributes=refusal.attributes()).end()
                return refusal.answer()
            identity = await keep(
                "INSERT INTO reports (received, text, nock, platform) VALUES (%s, %s, %s, %s)"
                " RETURNING id",
                (text, nock, platform),
            )
            tracer.start_span(
                "report.kept", attributes={"row_id": identity, "text_chars": len(text)}
            ).end()
        return JSONResponse({"id": identity}, 201)

    @app.post("/docs")
    async def publish(request: Request) -> JSONResponse:
        with tracer.start_as_current_span("docs", attributes=size(request)):
            try:
                bundle = await read(request, "/docs", lambda sent: docs.bundle(sent, public))
                async with pool.connection() as connection:
                    cursor = await connection.execute(
                        "INSERT INTO docs (min_cli, version, bundle, received)"
                        " VALUES (%s, %s, %s, %s) ON CONFLICT (min_cli) DO UPDATE"
                        " SET version = excluded.version, bundle = excluded.bundle,"
                        " received = excluded.received WHERE docs.version <= excluded.version"
                        " RETURNING version",
                        (bundle.min_cli, bundle.version, bundle.text, now()),
                    )
                    if await cursor.fetchone() is None:
                        raise Refusal(
                            409,
                            f"a newer bundle for nock {bundle.min_cli} is kept already",
                            "older",
                        )
            except Refusal as refusal:
                tracer.start_span("docs.refused", attributes=refusal.attributes()).end()
                return refusal.answer()
            tracer.start_span(
                "docs.kept",
                attributes={"min_cli": bundle.min_cli, "version": bundle.version},
            ).end()
        return JSONResponse({"min_cli": bundle.min_cli, "version": bundle.version}, 201)

    @app.get("/docs/{cli}")
    async def served(cli: str) -> Response:
        if not docs.SEMANTIC.fullmatch(cli):
            return JSONResponse({"error": "the version is MAJOR.MINOR.PATCH"}, 400)
        async with pool.connection() as connection:
            cursor = await connection.execute("SELECT min_cli, version, bundle FROM docs")
            rows = await cursor.fetchall()
        fitting = [row for row in rows if docs.release(row[0]) <= docs.release(cli)]
        with tracer.start_as_current_span(
            "docs_asked", attributes={"cli": cli, "found": bool(fitting)}
        ):
            if not fitting:
                return JSONResponse({"error": f"no docs for nock {cli}"}, 404)
            newest = max(fitting, key=lambda row: row[1])
        return Response(newest[2], media_type="application/json")

    return Edge(app, limit, now)


def size(request: Request) -> dict[str, int]:
    """The span's start attributes: the body's announced length, when it has a sound one."""
    length = request.headers.get("content-length", "")
    return {"bytes": int(length)} if length.isdigit() else {}
