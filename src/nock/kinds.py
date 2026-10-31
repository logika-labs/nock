"""The kinds of reflection round. Each is a `reflect.Round` — its name, its
skill, when it can run and is due, what it reads, the files its lead writes,
the checks its end must pass — and adding one is an entry here and its skill
in `briefs/`. `nock reflect` starts the default kind (nock's own) and
`nock reflect KIND` another; each finishes with `… finish JSON`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nock.logika import LogikaRound
from nock.reflect import Reflection, Round

if TYPE_CHECKING:
    from nock.project import Project

KINDS: dict[str, type[Round]] = {kind.kind: kind for kind in (Reflection, LogikaRound)}
# Words after `nock reflect` that are its commands, so never a kind's name.
RESERVED = ("finish",)
DEFAULT = next(kind for kind in KINDS.values() if kind.default)

assert not set(KINDS) & set(RESERVED), "a kind of round is named like a command of `reflect`"


def kinds(project: Project) -> list[Round]:
    """A round of every kind, for `project`; the default first."""
    return [kind(project) for kind in KINDS.values()]


def offered(project: Project) -> list[Round]:
    """The kinds other than the default that can run here: they are offered
    to the owner, never due on their own."""
    return [kind for kind in kinds(project) if not kind.default and not kind.unavailable()]
