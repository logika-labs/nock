"""What the owner says into a chat, made text: the studio forwards a recording
to the Whisper server `studio.transcribe_url` names, in the form OpenAI's
`/v1/audio/transcriptions` takes (and whisper.cpp's server and
faster-whisper-server take too): multipart, the audio as `file`, with
`model` and `response_format`. Nothing is sent while no URL is set."""

from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from nock.configuration import Configuration
from nock.errors import ExternalError, PreconditionError, UsageError

if TYPE_CHECKING:
    from nock.project import Project

ENDPOINT = "/v1/audio/transcriptions"
# The longest a transcription may take, in seconds: a minute of speech is a few seconds locally.
DEADLINE = 120
SUFFIXES = {
    "webm": ".webm",
    "ogg": ".ogg",
    "mp4": ".m4a",
    "mpeg": ".mp3",
    "wav": ".wav",
    "x-wav": ".wav",
}
HINT = (
    "Transcription is off: set a Whisper server in the studio's settings (the gear),"
    " or `transcribe_url` under `[studio]` in .nock/config.toml"
    " (or .nock/local/config.toml, for this machine only) — e.g."
    ' "https://api.openai.com/v1/audio/transcriptions", or a local whisper.cpp or'
    " faster-whisper-server — then reload the page."
)


class Transcription:
    """The settings under `[studio]`: `transcribe_url`, the endpoint (a bare
    server or `…/v1` gets `/v1/audio/transcriptions` added); `transcribe_model`;
    `transcribe_key_variable`, the environment variable holding its key, sent
    as a bearer token — the key itself is never in the configuration."""

    def __init__(self, project: Project) -> None:
        # Read afresh, so a URL set while the studio runs counts at the next reload.
        configuration = Configuration(
            [project.code_path("config.toml"), project.local / "config.toml"]
        )
        self.url = str(configuration.get("studio.transcribe_url") or "").strip()
        self.model = str(configuration.get("studio.transcribe_model") or "whisper-1").strip()
        self.variable = str(configuration.get("studio.transcribe_key_variable") or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def endpoint(self) -> str:
        parts = urllib.parse.urlsplit(self.url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise PreconditionError(f"studio.transcribe_url is {self.url!r}: not an http(s) URL")
        path = parts.path.rstrip("/")
        if not path:
            path = ENDPOINT
        elif path.endswith("/v1"):
            path += ENDPOINT.removeprefix("/v1")
        return urllib.parse.urlunsplit(parts._replace(path=path))

    def headers(self, boundary: str) -> dict[str, str]:
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if self.variable:
            key = os.environ.get(self.variable, "").strip()
            if not key:
                raise PreconditionError(
                    f"studio.transcribe_key_variable names {self.variable}, which is not set"
                    " where the studio runs: set it, and start the studio again"
                )
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def transcribe(self, audio: bytes, kind: str) -> str:
        """The text of a recording (`kind` its media type, `audio/webm`)."""
        if not self.enabled:
            raise PreconditionError(HINT)
        if not audio:
            raise UsageError("the recording is empty")
        subtype = kind.split(";")[0].strip().partition("/")[2]
        name = f"recording{SUFFIXES.get(subtype, '.webm')}"
        boundary = f"nock-{secrets.token_hex(12)}"
        fields = {"model": self.model, "response_format": "json"}
        body = b"".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n'.encode()
            for field, value in fields.items()
        )
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: {kind.split(';')[0].strip() or 'audio/webm'}\r\n\r\n"
        ).encode()
        body += audio + f"\r\n--{boundary}--\r\n".encode()
        endpoint = self.endpoint()
        request = urllib.request.Request(endpoint, body, self.headers(boundary), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=DEADLINE) as response:
                answer = response.read().decode(errors="replace")
        except urllib.error.HTTPError as error:
            said = error.read().decode(errors="replace").strip()
            raise ExternalError(
                f"the Whisper server at {endpoint} answered {error.code}: {said[:300] or error.reason}"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise ExternalError(
                f"no answer from the Whisper server at {endpoint}: {reason}"
            ) from error
        try:
            parsed = json.loads(answer)
        except json.JSONDecodeError:
            return answer.strip()
        text = parsed.get("text") if isinstance(parsed, dict) else None
        if not isinstance(text, str):
            raise ExternalError(f"the Whisper server at {endpoint} gave no `text`: {answer[:300]}")
        return text.strip()
