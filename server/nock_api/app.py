"""The ASGI app: `GET /health`, `POST /reflections`, `POST /usage`, and the edge every request passes.

Every `POST` answers `201` with `{"id": N}`, or `{"error": "…"}` with `400` naming what is wrong, `411`
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
from fastapi.responses import JSONResponse
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from nock_api import rules
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
    largest = rules.LARGEST[path]
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


def create(database_url: str, now: Callable[[], datetime], limit: Limit) -> ASGIApp:
    """The app over the database at `database_url`, its rows received at `now()`, its posts limited by
    `limit`. The connection pool opens and closes with the app's lifespan."""
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

    return Edge(app, limit, now)


def size(request: Request) -> dict[str, int]:
    """The span's start attributes: the body's announced length, when it has a sound one."""
    length = request.headers.get("content-length", "")
    return {"bytes": int(length)} if length.isdigit() else {}
