"""Review notifications: when it is the owner's turn in a topic (its review
is ready, an agent answered them in its chat, or proposed something), the nock process that records it tells them, once
per topic per `WINDOW`: in the studio's page while one is watching (`WATCH`,
which the running studio keeps), else as a native desktop notification whose
click opens the studio at what it tells of. What it tells is the timeline's
event (`nock.timeline`): the one the agent just wrote, its key kept with the
notification, so the Timeline and the notifications are one source. Each is
a row of `notifications`, which the page reads; no display (CI, a headless
agent) shows nothing."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.errors import PreconditionError
from nock.utils import now, parse_moment, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

# Seconds after a topic's notification in which it gets no other: a burst is one.
WINDOW = 300
# The running studio's record, in `.nock/local/`: its process, its address and
# how its page last said it is watched.
WATCH = "studio.json"
# nock's logo, the favicon's n, shown with every notification: packaged, so a vendored copy has it.
ICON = Path(__file__).resolve().parent / "pages" / "icon.png"
# Seconds a page's word on how it is watched holds: a hidden tab's timers run
# about once a minute.
WATCHED = 90


class Reason(StrEnum):
    REVIEW = "review"
    """The topic's review is ready (a new version of it, or the topic moved to review)."""
    ANSWERED = "answered"
    """An agent answered the owner in the topic's chat."""
    PROPOSED = "proposed"
    """An agent proposed something for the owner to accept or reject."""


class Watching(StrEnum):
    """How a studio page is watched, as it says at each poll."""

    FOCUSED = "focused"
    """In front of the owner: it shows a cue in the page."""
    NOTIFYING = "notifying"
    """Away, with the browser's notifications allowed: it shows one."""
    UNWATCHED = "unwatched"
    """Away, without them: the desktop is told instead."""


class Shown(StrEnum):
    STUDIO = "studio"
    DESKTOP = "desktop"
    NOWHERE = "nowhere"
    """No page watching and no display."""


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def wording(topic: str, reason: Reason, row: dict[str, Any]) -> str:
    """What the notification says: why it is the owner's turn, and what waits."""
    proposals = row.get("open") or 0
    waiting = f"{plural(proposals, 'proposal')} to decide" if proposals else ""
    if reason is Reason.REVIEW:
        return f"{topic}: the review is ready" + (f", {waiting}" if waiting else "")
    if reason is Reason.ANSWERED:
        return f"{topic}: an agent answered you"
    return f"{topic}: a new proposal" + (f" ({waiting})" if proposals > 1 else "")


def display() -> bool:
    """Whether this process has a screen to show a notification on: never in
    CI; on macOS only in the user's graphical login session (not over ssh, not
    a daemon); on Linux with an X or Wayland display."""
    if os.environ.get("CI", "").lower() not in ("", "0", "false"):
        return False
    if sys.platform == "darwin":
        try:
            manager = subprocess.run(
                ["launchctl", "managername"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return False
        return manager == "Aqua"
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return False


def desktop_command(
    title: str, text: str, address: str, topic: str, platform: str = sys.platform
) -> list[str] | None:
    """The command that shows it, with nock's logo. On macOS `terminal-notifier`
    when installed, whose click opens the address; otherwise AppleScript's
    notification, which cannot open anything on a click (nor show a picture of
    its own), so its text names the address. On Linux `notify-send`, the
    address in its body."""
    if platform == "darwin":
        notifier = shutil.which("terminal-notifier")
        if notifier:
            return [
                notifier,
                *("-title", title, "-message", text, "-open", address),
                *("-group", f"nock-{topic}"),
                *("-appIcon", str(ICON), "-contentImage", str(ICON)),
            ]
        script = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"
        return ["osascript", "-e", script, title, f"{text} — {address}"]
    if platform.startswith("linux"):
        sender = shutil.which("notify-send")
        if sender:
            return [sender, "--app-name=nock", f"--icon={ICON}", title, f"{text}\n{address}"]
    return None


def alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def seconds_between(earlier: str, later: str) -> float:
    start, end = parse_moment(earlier), parse_moment(later)
    if start is None or end is None:
        return float("inf")
    return (end - start).total_seconds()


class Notifications:
    def __init__(self, project: Project) -> None:
        self.project = project

    @property
    def enabled(self) -> bool:
        return bool(self.project.configuration.get("notifications", True))

    @property
    def path(self) -> Path:
        return self.project.local / WATCH

    def studio(self) -> dict[str, Any] | None:
        """The running studio's record; None when none runs."""
        try:
            record = read_json(self.path)
        except (FileNotFoundError, PreconditionError):
            return None
        return record if isinstance(record, dict) and alive(record.get("pid")) else None

    def started(self, address: str) -> None:
        """The studio, starting: where it answers, no page watching yet."""
        write_json(self.path, {"pid": os.getpid(), "address": address})

    def watched(self, seen: Watching, at: str | None = None) -> None:
        """A page's word, at its poll, on how it is watched."""
        record = self.studio() or {"pid": os.getpid(), "address": ""}
        write_json(self.path, {**record, "seen": str(seen), "moment": at or now()})

    def address(self, topic: str, fragment: str | None = None) -> str:
        """The studio at the topic, or at the place FRAGMENT names: the running
        one's address, else the configured port's."""
        running = (self.studio() or {}).get("address")
        base = running or f"http://127.0.0.1:{self.project.configuration.get('studio.port')}/"
        return f"{base}{fragment or f'#/t/{topic}'}"

    def page_watching(self, at: str) -> bool:
        record = self.studio()
        if record is None or record.get("seen") not in (Watching.FOCUSED, Watching.NOTIFYING):
            return False
        return seconds_between(record.get("moment") or "", at) <= WATCHED

    def tell(
        self,
        topic: str,
        reason: Reason,
        row: dict[str, Any],
        at: str | None = None,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """It is the owner's turn in TOPIC: record it and show it, unless they
        were told of this topic less than `WINDOW` seconds ago (or turned
        notifications off); the row recorded, or None. EVENT is the timeline's
        event it tells of, its address where a click leads."""
        if not self.enabled:
            return None
        at = at or now()
        with self.project.lock("notifications"):
            last = self.project.store.rows(
                "SELECT moment FROM notifications WHERE topic = ? ORDER BY id DESC LIMIT 1",
                (topic,),
            )
            if last and seconds_between(last[0]["moment"], at) < WINDOW:
                return None
            text = wording(topic, reason, row)
            if self.page_watching(at):
                shown = Shown.STUDIO
            else:
                shown = Shown.DESKTOP if display() else Shown.NOWHERE
            kept: dict[str, Any] = {
                "moment": at,
                "topic": topic,
                "reason": str(reason),
                "text": text,
                "shown": str(shown),
                "event": (event or {}).get("key"),
                "address": (event or {}).get("address") or f"#/t/{topic}",
                "preview": (event or {}).get("preview") or "",
            }
            kept["id"] = self.project.store.insert("notifications", kept)
        if shown is Shown.DESKTOP:
            self.show(topic, text, kept["address"])
        return kept

    def show(self, topic: str, text: str, address: str | None = None) -> None:
        """On the desktop, left to run on its own: the caller does not wait."""
        command = desktop_command(
            f"nock · {self.project.root.name}", text, self.address(topic, address), topic
        )
        if command is None:
            return
        with contextlib.suppress(OSError):
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    def since(self, after: int | None) -> dict[str, Any]:
        """What a page polling has not shown: the notifications after id
        AFTER (none on its first poll, which only learns the latest id)."""
        latest = self.project.store.rows("SELECT MAX(id) AS id FROM notifications")[0]["id"] or 0
        if after is None:
            return {"latest": latest, "notifications": []}
        rows = self.project.store.rows(
            "SELECT * FROM notifications WHERE id > ? ORDER BY id LIMIT 20", (after,)
        )
        for row in rows:
            row["address"] = row.get("address") or f"#/t/{row['topic']}"
        return {"latest": latest, "notifications": rows}
