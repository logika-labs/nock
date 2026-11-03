"""Writing to nock's makers: `nock report` sends what the user wrote — something
nock lacks, something broken or confusing — with nock's version and the
platform and nothing else, and only on the user's word: asked on a terminal,
`--yes` where there is none to ask on."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from nock.errors import ExternalError, PolicyError, UsageError
from nock.releases import VERSION

if TYPE_CHECKING:
    from nock.project import Project

# The longest text sent; api.nock.dev refuses more.
LONGEST = 10_000
NO_TERMINAL = (
    "nothing sent: with no terminal to ask on, `nock report` sends only with --yes. Show the"
    " user exactly what would be sent (below) and pass --yes only once they have explicitly"
    " said to send it."
)


class Reports:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.endpoint = str(project.configuration.get("endpoints.reports"))

    def outgoing(self, text: str | None) -> dict[str, str]:
        """The body as it would be sent: the text given, else stdin's when it is
        not a terminal, with nock's version and the platform."""
        if text is None and sys.stdin.isatty():
            raise UsageError('say what to send: `.nock/nock report "TEXT"`, or the text on stdin')
        written = (sys.stdin.read() if text is None else text).strip()
        if not written:
            raise UsageError("nothing to send: the text is empty")
        if len(written) > LONGEST:
            raise UsageError(f"the text is {len(written)} characters; at most {LONGEST} are sent")
        return {"text": written, "nock": VERSION, "platform": sys.platform}

    def report(self, text: str | None, yes: bool) -> dict[str, Any]:
        body = self.outgoing(text)
        if not yes:
            self.ask(body)
        post = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "User-Agent": f"nock/{VERSION}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(post, timeout=30) as response:
                answer = json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            said = error.read().decode(errors="replace").strip()
            raise ExternalError(f"{self.endpoint} refused it ({error.code}): {said}") from error
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise ExternalError(f"could not reach {self.endpoint}: {error}") from error
        return {"sent": body, "to": self.endpoint, "id": answer.get("id")}

    def ask(self, body: dict[str, str]) -> None:
        """Show the user what would go and ask; on no terminal, or anything but
        a yes, nothing is sent."""
        if not sys.stdin.isatty():
            raise PolicyError(NO_TERMINAL, {"would_send": body, "to": self.endpoint})
        sys.stderr.write(
            f"This goes to nock's makers ({self.endpoint}):\n\n"
            f"{json.dumps(body, indent=2, ensure_ascii=False)}\n\nSend it? [y/N] "
        )
        sys.stderr.flush()
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            raise PolicyError("nothing sent: the answer was not yes")
