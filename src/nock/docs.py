"""nock's documentation for agents (`nock docs`): one short article per term,
each a file in `terms/` named by its dotted term (`tools.caching.md`), opening
with front matter — `term`, `aliases`, `description` — between `---` lines.
A dotted term is a child of the term before its last dot, which must exist;
an article lists its children."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from nock.errors import NotFoundError, PreconditionError

TERMS = Path(__file__).resolve().with_name("terms")
# The longest article and description, in characters.
LIMIT = 500
DESCRIPTION_LIMIT = 100
FIELDS = ("term", "aliases", "description")
NAME = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*$")
SUGGESTIONS = 3


class TermError(PreconditionError):
    """A term file that breaks the rules, naming the file."""


@dataclass(frozen=True)
class Term:
    term: str
    aliases: tuple[str, ...]
    description: str
    article: str

    @property
    def names(self) -> tuple[str, ...]:
        return (self.term, *self.aliases)

    @property
    def parent(self) -> str | None:
        return self.term.rpartition(".")[0] or None


def parse(path: Path) -> Term:
    """The term in `path`, or a TermError saying what is wrong with it."""

    def fail(problem: str) -> TermError:
        return TermError(f"{path.name}: {problem}")

    source = path.read_text()
    if not source.startswith("---\n") or "\n---\n" not in source[3:]:
        raise fail("no front matter: `---`, `term`, `aliases`, `description`, `---`")
    front, _, body = source[4:].partition("\n---\n")
    fields: dict[str, str] = {}
    for line in front.splitlines():
        key, colon, value = line.partition(":")
        if not colon or key.strip() not in FIELDS:
            raise fail(f"`{line}` is not one of the fields {', '.join(FIELDS)}")
        if key.strip() in fields:
            raise fail(f"`{key.strip()}` twice")
        fields[key.strip()] = value.strip()
    missing = [field for field in FIELDS if field not in fields]
    if missing:
        raise fail(f"missing {', '.join(missing)}")
    term = fields["term"]
    aliases_text = fields["aliases"]
    if not (aliases_text.startswith("[") and aliases_text.endswith("]")):
        raise fail("`aliases` is not a list: `[a, b]`, `[]` for none")
    aliases = tuple(alias.strip() for alias in aliases_text[1:-1].split(",") if alias.strip())
    description = fields["description"]
    if description.startswith('"'):
        try:
            description = str(json.loads(description))
        except ValueError as error:
            raise fail(f"`description` is not a quoted string: {error}") from error
    for name in (term, *aliases):
        if not NAME.match(name):
            raise fail(f"`{name}` is not a term: lowercase letters, digits and `-`, joined by `.`")
    if path.name != f"{term}.md":
        raise fail(f"the term is `{term}`, so the file is {term}.md")
    if not description or len(description) > DESCRIPTION_LIMIT:
        raise fail(f"the description is {len(description)} characters; 1 to {DESCRIPTION_LIMIT}")
    article = body.strip()
    if not article or len(article) > LIMIT:
        raise fail(f"the article is {len(article)} characters; 1 to {LIMIT}")
    return Term(term, aliases, description, article)


class Docs:
    """Every term in `directory`, parents before their children."""

    def __init__(self, directory: Path = TERMS) -> None:
        terms = [parse(path) for path in directory.glob("*.md")]
        self.terms = sorted(terms, key=lambda term: term.term.split("."))

    def problems(self) -> list[str]:
        """What is wrong across the terms: a name taken twice, a child without its parent."""
        problems: list[str] = []
        owners: dict[str, str] = {}
        for term in self.terms:
            for name in term.names:
                if name in owners:
                    problems.append(f"`{name}` names both {owners[name]} and {term.term}")
                owners.setdefault(name, term.term)
        known = {term.term for term in self.terms}
        problems += [
            f"{term.term}: no term `{term.parent}` to be a child of"
            for term in self.terms
            if term.parent and term.parent not in known
        ]
        return problems

    def find(self, word: str) -> Term | None:
        word = word.lower()
        return next((term for term in self.terms if word in term.names), None)

    def children(self, term: Term) -> list[Term]:
        return [child for child in self.terms if child.parent == term.term]

    def index(self) -> dict[str, str]:
        return {term.term: term.description for term in self.terms}

    def article(self, term: Term) -> str:
        children = self.children(term)
        if not children:
            return term.article
        more = [f"- `.nock/nock docs {child.term}`: {child.description}" for child in children]
        return "\n\n".join([term.article, "More:\n" + "\n".join(more)])

    def read(self, words: list[str]) -> str:
        """The articles `words` name, one after another; NotFoundError for any
        name that isn't a term, with the closest."""
        found: list[Term] = []
        for word in words:
            term = self.find(word)
            if term is None:
                raise NotFoundError(
                    f"`{word}` is not a term; the closest are below, and `.nock/nock docs` lists them all",
                    {term.term: term.description for term in self.closest(word)},
                )
            found.append(term)
        if len(found) == 1:
            return self.article(found[0])
        return "\n\n".join(f"# {term.term}\n\n{self.article(term)}" for term in found)

    def closest(self, word: str) -> list[Term]:
        """The terms nearest `word`: those with a name it nearly spells, then
        those whose articles mention it most, then those with the most alike names."""
        word = word.lower()
        by_name = {name: term for term in self.terms for name in term.names}
        near = difflib.get_close_matches(word, by_name, n=len(by_name), cutoff=0.6)
        pattern = re.compile(rf"(?<![\w-]){re.escape(word)}(?![\w-])", re.IGNORECASE)
        counted = [
            (len(pattern.findall(f"{term.description}\n{term.article}")), term)
            for term in self.terms
        ]
        mentioning = [term for count, term in sorted(counted, key=lambda pair: -pair[0]) if count]
        alike = sorted(by_name, key=lambda name: -difflib.SequenceMatcher(None, word, name).ratio())
        picked: list[Term] = []
        for term in [
            *(by_name[name] for name in near),
            *mentioning,
            *(by_name[name] for name in alike),
        ]:
            if term not in picked:
                picked.append(term)
        return picked[:SUGGESTIONS]
