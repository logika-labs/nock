"""`nock report`: what the user wrote goes to nock's makers with nock's version
and the platform and nothing else, asked on a terminal, and with no terminal
only with `--yes`; the agents are told the channel exists."""

from __future__ import annotations

import json
import os
import pty
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from nock.project import Project
from nock.releases import VERSION

from .conftest import nock

TEXT = "I need nock to list the decisions a commit touched."


class Receiver(BaseHTTPRequestHandler):
    received: list[dict[str, Any]] = []
    status = 201

    def do_POST(self) -> None:
        self.received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        answer = {"id": len(self.received)} if self.status == 201 else {"error": "try again later"}
        body = json.dumps(answer).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *arguments: object) -> None:
        pass


class Endpoint:
    """A real server on this machine standing in for api.nock.dev's `/reports`."""

    def __init__(self, project: Project) -> None:
        self.received: list[dict[str, Any]] = []
        self.handler = type("Handler", (Receiver,), {"received": self.received})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.address = f"http://127.0.0.1:{self.server.server_address[1]}/reports"
        local = project.root / ".nock" / "local" / "config.toml"
        local.write_text(local.read_text() + f'[endpoints]\nreports = "{self.address}"\n')

    def refuse(self, status: int) -> None:
        self.handler.status = status

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def endpoint(project: Project) -> Iterator[Endpoint]:
    running = Endpoint(project)
    yield running
    running.stop()


def on_a_terminal(directory: Path, answer: str, *arguments: str) -> tuple[int, str, str]:
    """The CLI with a terminal for its stdin, as someone typing at it; `answer`
    is what they type."""
    controller, terminal = pty.openpty()
    try:
        process = subprocess.Popen(
            [str(directory / ".nock" / "nock"), *arguments],
            cwd=directory,
            stdin=terminal,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "NOCK_PYTHON": sys.executable},
        )
        os.write(controller, answer.encode() + b"\n")
        stdout, stderr = process.communicate(timeout=60)
    finally:
        os.close(controller)
        os.close(terminal)
    return process.returncode, stdout, stderr


def test_without_a_terminal_nothing_is_sent_without_yes(
    project: Project, endpoint: Endpoint
) -> None:
    refused = nock(project.root, "report", TEXT, "--json")
    assert refused.returncode == 43
    assert "--yes" in refused.stderr and "explicitly said to send it" in refused.stderr
    shown = json.loads(refused.stdout)
    assert shown == {
        "would_send": {"text": TEXT, "nock": VERSION, "platform": sys.platform},
        "to": endpoint.address,
    }
    assert endpoint.received == []


def test_with_yes_the_text_version_and_platform_go_and_the_id_comes_back(
    project: Project, endpoint: Endpoint
) -> None:
    sent = nock(project.root, "report", f"  {TEXT}\n", "--yes", "--json")
    assert sent.returncode == 0, sent.stderr
    body = {"text": TEXT, "nock": VERSION, "platform": sys.platform}
    assert endpoint.received == [body]
    assert json.loads(sent.stdout) == {"sent": body, "to": endpoint.address, "id": 1}
    piped = nock(project.root, "report", "--yes", stdin="Second, from stdin.\n")
    assert piped.returncode == 0, piped.stderr
    assert endpoint.received[1]["text"] == "Second, from stdin."
    assert "id: 2" in piped.stdout


def test_empty_or_too_long_text_is_refused_before_anything_is_sent(
    project: Project, endpoint: Endpoint
) -> None:
    assert nock(project.root, "report", "   ", "--yes").returncode == 40
    assert nock(project.root, "report", "--yes", stdin="").returncode == 40
    long = nock(project.root, "report", "x" * 10_001, "--yes")
    assert long.returncode == 40 and "at most 10000" in long.stderr
    assert endpoint.received == []


def test_a_refusal_or_no_server_is_said_plainly(project: Project, endpoint: Endpoint) -> None:
    endpoint.refuse(429)
    refused = nock(project.root, "report", TEXT, "--yes")
    assert refused.returncode == 52 and "(429): " in refused.stderr
    assert "try again later" in refused.stderr
    endpoint.stop()
    unreachable = nock(project.root, "report", TEXT, "--yes")
    assert unreachable.returncode == 52 and "could not reach" in unreachable.stderr


def test_on_a_terminal_it_shows_what_goes_and_sends_only_on_a_yes(
    project: Project, endpoint: Endpoint
) -> None:
    code, _, stderr = on_a_terminal(project.root, "n", "report", TEXT)
    assert code == 43 and "nothing sent" in stderr
    assert endpoint.address in stderr and f'"text": "{TEXT}"' in stderr and "[y/N]" in stderr
    assert endpoint.received == []
    code, stdout, stderr = on_a_terminal(project.root, "y", "report", TEXT, "--json")
    assert code == 0, stderr
    assert endpoint.received == [{"text": TEXT, "nock": VERSION, "platform": sys.platform}]
    assert json.loads(stdout)["id"] == 1


def test_agents_are_told_they_can_write_to_the_makers(project: Project) -> None:
    primer = (project.root / ".nock" / "context.md").read_text()
    assert '`.nock/nock report "…"`' in primer and "go-ahead" in primer
    assert "report" in nock(project.root, "docs", "report").stdout
