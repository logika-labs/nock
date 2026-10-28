"""nock's releases, published on PyPI as `nock`: this one's version, the
latest one — looked up at most once a day, so a session the human starts can
say when there is a newer one — and a release's files, which `nock upgrade`
merges into the vendored core."""

from __future__ import annotations

import io
import json
import re
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from nock.errors import ExternalError, NotFoundError
from nock.utils import now, parse_moment, read_json, write_json

if TYPE_CHECKING:
    from pathlib import Path

    from nock.project import Project

VERSION = "0.3.0"
NAME = "nock"
# The source an install or upgrade names to mean PyPI, rather than a git URL or a checkout.
PYPI = "pypi"
INDEX = f"https://pypi.org/pypi/{NAME}"
# How long a looked-up latest version stands before it is looked up again.
CHECK_EVERY = 86400
# How long a session start waits on PyPI before it gives up, in seconds.
TIMEOUT = 2.0


def parsed(version: str) -> tuple[int, ...]:
    """A version, comparable: `0.10.1` → (0, 10, 1); anything after the numbers is ignored."""
    return tuple(int(part) for part in re.findall(r"\d+", version.split("+")[0])[:3])


class Releases:
    def __init__(self, index: str = INDEX, timeout: float = 30.0) -> None:
        self.index = index.rstrip("/")
        self.timeout = timeout

    def metadata(self, version: str | None = None) -> dict[str, Any]:
        url = f"{self.index}/{version}/json" if version else f"{self.index}/json"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise NotFoundError(
                    f"no release {version or ''} of {NAME} at {self.index}"
                ) from error
            raise ExternalError(f"{url}: {error}") from error
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise ExternalError(f"could not reach {url}: {error}") from error

    def latest(self) -> str:
        return str(self.metadata()["info"]["version"])

    def files(self, version: str) -> dict[str, bytes]:
        """The `nock` package of a release, by path relative to it, from its wheel."""
        wheels = [
            item for item in self.metadata(version)["urls"] if item["packagetype"] == "bdist_wheel"
        ]
        if not wheels:
            raise NotFoundError(f"{NAME} {version} has no wheel")
        try:
            with urllib.request.urlopen(wheels[0]["url"], timeout=self.timeout) as response:
                archive = zipfile.ZipFile(io.BytesIO(response.read()))
        except (urllib.error.URLError, TimeoutError, zipfile.BadZipFile) as error:
            raise ExternalError(f"could not download {NAME} {version}: {error}") from error
        return {
            name.removeprefix("nock/"): archive.read(name)
            for name in archive.namelist()
            if name.startswith("nock/") and not name.endswith("/")
        }


class Updates:
    """Whether a newer nock than the vendored one is out — looked up at most
    once a day, quietly, and never when `upgrade.check` is off."""

    def __init__(self, project: Project) -> None:
        self.project = project

    @property
    def cache(self) -> Path:
        return self.project.local / "latest.json"

    def installed(self) -> str:
        version = self.project.root / ".nock" / "core" / "VERSION.json"
        return str(read_json(version).get("version") or VERSION) if version.is_file() else VERSION

    def newer(self) -> str | None:
        """The latest version, when it is newer than the vendored one."""
        settings = self.project.configuration
        if not settings.get("upgrade.check"):
            return None
        kept = read_json(self.cache) if self.cache.is_file() else {}
        checked = parse_moment(kept.get("checked"))
        if checked is None or (datetime.now(UTC) - checked).total_seconds() > CHECK_EVERY:
            try:
                latest: str | None = Releases(str(settings.get("upgrade.index")), TIMEOUT).latest()
            except (ExternalError, NotFoundError, KeyError):
                latest = None
            kept = {"checked": now(), "latest": latest}
            write_json(self.cache, kept)
        latest = kept.get("latest")
        if latest and parsed(str(latest)) > parsed(self.installed()):
            return str(latest)
        return None
