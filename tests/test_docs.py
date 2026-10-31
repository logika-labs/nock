"""`nock docs`: the agents' documentation as short terms, each held to its
rules, and the briefs pointing only at terms that exist."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nock.docs import DESCRIPTION_LIMIT, LIMIT, NAME, TERMS, Docs, TermError
from nock.project import Project

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


def write_term(directory: Path, term: str, front: str, article: str = "An article.") -> None:
    (directory / f"{term}.md").write_text(f"---\n{front}\n---\n\n{article}\n")


def test_every_term_holds_to_the_rules() -> None:
    docs = Docs()
    assert docs.problems() == []
    assert len(docs.terms) == len(list(TERMS.glob("*.md")))
    for term in docs.terms:
        assert len(term.article) <= LIMIT and len(term.description) <= DESCRIPTION_LIMIT
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
    write_term(tmp_path, "eval.runs", "term: eval.runs\naliases: []\ndescription: Runs")
    assert Docs(tmp_path).problems() == [
        "`tool` names both tool and tools",
        "eval.runs: no term `eval` to be a child of",
    ]


def test_nock_docs_lists_the_terms_reads_them_and_answers_a_miss(project: Project) -> None:
    listed = nock(project.root, "docs", "--json")
    assert listed.returncode == 0, listed.stderr
    index = json.loads(listed.stdout)
    assert index["tools.caching"] == Docs().find("cache").description  # pyright: ignore[reportOptionalMemberAccess]
    assert "decisions.questions" in index and "studio" in index

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
    sources = [*PACKAGE.joinpath("briefs").rglob("*.md"), *PACKAGE.parent.parent.glob("*.md")]
    for path in sources:
        for pointer in POINTER.findall(path.read_text()):
            for word in pointer.split():
                if word != "--full":
                    assert docs.find(word), f"{path.name} points at `{word}`, not a term"
                    named.setdefault(path.name, set()).add(word)
    toolbox = named["process.md"]
    for term in docs.terms:
        if term.term.split(".")[0] in FRAMEWORK:
            assert term.term in toolbox, f"the toolbox brief doesn't point at {term.term}"
    for brief in ("SKILL.md", "consult.md", "elaborate.md", "knowledge.md", "nock.md"):
        assert brief in named, brief
