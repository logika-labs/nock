"""`nock docs`: the documentation as short terms for agents and guides for people, each
held to its rules, and the briefs pointing only at terms that exist."""

from __future__ import annotations

import fnmatch
import json
import re
import sqlite3
from pathlib import Path

import pytest

from nock import rounds
from nock.docs import (
    BRIEF_LIMIT,
    BRIEFS,
    DESCRIPTION_LIMIT,
    GUIDE_LIMIT,
    GUIDES,
    LIMIT,
    NAME,
    TERMS,
    Docs,
    TermError,
)
from nock.project import Project
from nock.store import SCHEMA

from .conftest import nock

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "nock"
# The terms the toolbox part of a reflection round reads before it writes:
# everything the framework guide used to hold.
FRAMEWORK = (
    "tools",
    "fixtures",
    "sh",
    "run",
    "output",
    "errors",
    "exit-codes",
    "checks",
    "hooks",
    "generators",
    "environment",
    "configuration",
    "telemetry",
    "logika",
)
POINTER = re.compile(r"nock docs((?: --full)?(?: [a-z0-9.-]+)+)")


def test_the_telemetry_tables_term_names_only_real_columns() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(SCHEMA)
    columns = {
        table: {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    term = Docs().find("telemetry.tables")
    assert term is not None
    article = term.article
    named = 0
    for sentence in article.split(". "):
        before, _, after = sentence.partition(":")
        tables = re.findall(r"`([a-z_]+)`", before)
        assert tables and set(tables) <= set(columns), sentence
        for column in re.findall(r"`([a-z_*]+)`", after):
            assert len(tables) == 1, sentence
            assert fnmatch.filter(columns[tables[0]], column), f"{tables[0]} has no {column}"
            named += 1
    assert named > 20


def write_term(directory: Path, term: str, front: str, article: str = "An article.") -> None:
    (directory / f"{term}.md").write_text(f"---\n{front}\n---\n\n{article}\n")


def test_every_term_holds_to_the_rules() -> None:
    docs = Docs()
    assert docs.problems() == []
    briefs = {path.stem for path in (TERMS / BRIEFS).glob("*.md")}
    guides = {path.stem for path in (TERMS / GUIDES).glob("*.md")}
    assert len(docs.terms) == len(list(TERMS.glob("*.md"))) + len(briefs) + len(guides)
    for term in docs.terms:
        limit = (
            BRIEF_LIMIT if term.term in briefs else GUIDE_LIMIT if term.term in guides else LIMIT
        )
        assert len(term.article) <= limit and len(term.description) <= DESCRIPTION_LIMIT
        assert all(NAME.match(name) for name in term.names)
    assert [term.term for term in docs.terms][:2] == ["checks", "checks.chains"]


@pytest.mark.parametrize(
    ("front", "article", "problem"),
    [
        ("term: tools\ndescription: x", "A.", "missing aliases"),
        ("term: tools\naliases: tool\ndescription: x", "A.", "`aliases` is not a list"),
        ("term: tools\naliases: []\ndescription: x\nroles: [a]", "A.", "`roles: [a]` is not"),
        ("term: Tools\naliases: []\ndescription: x", "A.", "`Tools` is not a term"),
        ("term: tool\naliases: []\ndescription: x", "A.", "so the file is tool.md"),
        ("term: tools\naliases: []\ndescription: " + "x" * 101, "A.", "description is 101"),
        ("term: tools\naliases: []\ndescription: x", "x" * 501, "article is 501"),
        ('term: tools\naliases: []\ndescription: "x', "A.", "not a quoted string"),
    ],
)
def test_a_term_that_breaks_a_rule_names_its_file_and_the_rule(
    tmp_path: Path, front: str, article: str, problem: str
) -> None:
    write_term(tmp_path, "tools", front, article)
    with pytest.raises(TermError) as refused:
        Docs(tmp_path)
    assert str(refused.value).startswith("tools.md: ") and problem in str(refused.value)


def test_names_are_unique_and_a_child_has_its_parent(tmp_path: Path) -> None:
    write_term(tmp_path, "tools", "term: tools\naliases: [tool]\ndescription: Tools")
    write_term(tmp_path, "tool", "term: tool\naliases: []\ndescription: Tool")
    write_term(tmp_path, "widgets.runs", "term: widgets.runs\naliases: []\ndescription: Runs")
    assert Docs(tmp_path).problems() == [
        "`tool` names both tool and tools",
        "widgets.runs: no term `widgets` to be a child of",
    ]


def test_nock_docs_lists_the_terms_reads_them_and_answers_a_miss(project: Project) -> None:
    listed = nock(project.root, "docs", "--json")
    assert listed.returncode == 0, listed.stderr
    index = json.loads(listed.stdout)
    assert index["tools.caching"] == Docs().find("cache").description  # pyright: ignore[reportOptionalMemberAccess]
    assert "topics.verdicts" in index and "studio" in index

    by_alias = nock(project.root, "docs", "CACHE")
    assert by_alias.returncode == 0 and by_alias.stdout.startswith("`@nock.command(cache=")
    parent = nock(project.root, "docs", "tools").stdout
    assert "More:\n- `.nock/nock docs tools.caching`: cache= replays" in parent
    several = nock(project.root, "docs", "fixtures", "exit-codes").stdout
    assert (
        several.startswith("# fixtures\n\nAs in pytest") and "\n\n# exit-codes\n\n0 yes." in several
    )

    missed = nock(project.root, "docs", "fixturs")
    assert missed.returncode == 44
    assert "`fixturs` is not a term" in missed.stderr
    suggested = [line.split(":")[0] for line in missed.stdout.splitlines()]
    assert len(suggested) == 3 and suggested[0] == "fixtures"
    nothing_alike = nock(project.root, "docs", "tools", "qqqq")
    assert nothing_alike.returncode == 44 and len(nothing_alike.stdout.splitlines()) == 3


def test_the_briefs_point_only_at_terms_and_the_toolbox_brief_at_the_framework() -> None:
    docs = Docs()
    named: dict[str, set[str]] = {}
    sources = [
        *PACKAGE.joinpath("briefs").rglob("*.md"),
        *(TERMS / BRIEFS).glob("*.md"),
        *(TERMS / GUIDES).glob("*.md"),
        *PACKAGE.parent.parent.glob("*.md"),
    ]
    for path in sources:
        for pointer in POINTER.findall(path.read_text()):
            for word in pointer.split():
                if word != "--full":
                    assert docs.find(word), f"{path.name} points at `{word}`, not a term"
                    named.setdefault(path.name, set()).add(word)
    toolbox = named["reflection.toolbox.md"]
    for term in docs.terms:
        if term.term.split(".")[0] in FRAMEWORK:
            assert term.term in toolbox, f"the toolbox brief doesn't point at {term.term}"
    for brief in ("consult.md", "reflection.map.md", "reflection.nock.md"):
        assert brief in named, brief


def test_every_skill_and_subagent_nock_installs_points_at_its_brief() -> None:
    """Their text lives in `nock docs`, so it always matches the vendored core
    and an upgrade never rewrites a skill: each keeps only its front matter
    and one line. A round's agents are its protocol's, named when installed."""
    docs = Docs()
    skills = list(PACKAGE.joinpath("briefs").rglob("SKILL.md"))
    agents = list(PACKAGE.joinpath("rounds").glob("*/*/agents/*.md"))
        "nock.toolbox", "nock.map", "nock.fit", "logika.rules", "logika.analytics",
        ,
    for path in skills + agents:
        front, _, body = path.read_text()[4:].partition("\n---\n")
        named = f"name: {path.parent.name}\n" if path.name == "SKILL.md" else ""
        assert front.startswith(f"{named}description: "), path
        if path.is_relative_to(PACKAGE / "rounds" / "audit"):
            assert body.strip().startswith("# "), path
            continue
        pointer = re.fullmatch(
            r"Run `\.nock/nock docs ([a-z.-]+)` and do what it says\.", body.strip()
        )
        assert pointer and docs.find(pointer.group(1)), path


def test_every_shipped_protocol_has_its_lead_s_brief_and_one_for_each_agent() -> None:
    manifests = rounds.manifests(None)
    assert set(manifests) == {
        "nock.toolbox", "nock.map", "nock.fit", "logika.rules", "logika.analytics",
        "nock.toolbox", "nock.map", "nock.fit", "logika.rules", "logika.analytics",
        "audit.performance", "audit.security", "audit.tests", "fuzz.api",
    }  # fmt: skip
    for manifest in manifests.values():
        assert (manifest.folder / rounds.LEAD).read_text().startswith("# "), manifest.name
        names = {agent["name"] for agent in manifest.data["agents"]}
        assert {path.stem for path in (manifest.folder / "agents").glob("*.md")} == names
        for source in manifest.data.get("material", {}).values():
            assert len(source) == 1 and set(source) <= {"python", "command", "topic", "git"}


def test_a_brief_is_printed_whole_however_long(project: Project) -> None:
    printed = nock(project.root, "docs", "reflection.logika.rules")
    assert printed.returncode == 0, printed.stderr
    article = Docs().find("reflection.logika.rules").article  # pyright: ignore[reportOptionalMemberAccess]
    assert len(article) > 8000 and printed.stdout.strip() == article


def test_every_guide_is_a_page_under_guide_with_its_title(project: Project) -> None:
    """The guides are the documentation for people: each a child of `guide`, opening with
    its title, printed whole however long, and listed by `nock docs guide`."""
    docs = Docs()
    guides = [term for term in docs.terms if term.term.startswith("guide.")]
    assert len(guides) == len(list((TERMS / GUIDES).glob("*.md"))) >= 7
    for guide in guides:
        assert guide.article.startswith("# ") and "\n" in guide.article, guide.term
    longest = max(guides, key=lambda guide: len(guide.article))
    assert len(longest.article) > 8000
    printed = nock(project.root, "docs", longest.term)
    assert printed.returncode == 0 and printed.stdout.strip() == longest.article
    listed = nock(project.root, "docs", "guide").stdout
    assert all(f"`.nock/nock docs {guide.term}`" in listed for guide in guides)
