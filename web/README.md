# nock.dev

The website, kept beside the code it documents. It is not part of nock: `nock
init` vendors `src/nock/` only, and the package is built from `src/` only.
Standard library only, like nock.

```
layout.html        every page's frame: the band and its menu, the main column, the footer
home.html          the home page's main column
legal/             privacy.md and terms.md, each with its plain-words summary (NAME-plain.md)
site/              style.css and fonts/; the pages are built into it (gitignored)
build.py           the pages: home, ../README.md → getting-started/ and docs/ (a page per
                   section, in a tab: Concepts, Evaluation, Reference), legal/ → privacy/, terms/
publish.py         build, and push to GitHub Pages
```

The column, the type scale and the look are the studio's (`src/nock/pages/`).

## Build

```sh
python3 web/build.py
python3 -m http.server -d web/site   # then open http://localhost:8000
```

The docs are the README, so edit the README, never `site/`. `DOCS` in `build.py`
places each of its `## ` sections: a page in a tab, with its line on the docs
index. `START` is Getting started, a page of its own, and `LEFT_OUT` stays on
PyPI only (Thanks). A section placed nowhere fails the build. A link between
sections lands on the right page, and an old one-page address, `/docs/#ANCHOR`,
is sent on to the page that has the heading now.

`TELEGRAM` in `build.py` is the community's link on every page: a placeholder
until the channel exists.

The legal pages show their summary above the full text while the tl;dr switch
is on (the default); the visitor's choice stays in their browser's
`localStorage`, as the privacy policy says. The full text is always shown.

## Publish

```sh
python3 web/publish.py --no-push   # build, stage and commit in web/pages/; show the change
python3 web/publish.py             # the same, then ask before pushing
```

The site is served by GitHub Pages from `logika-labs/nock.dev` (branch `main`,
the root). Publishing clones it into `web/pages/` (gitignored), replaces
everything but `.git` with `site/` plus `CNAME` (`nock.dev`) and `.nojekyll`,
commits, shows the change, and pushes only when you answer `y`.

## The API

api.nock.dev, where `nock share` sends a summary, nock its usage reports and
`nock report` what someone wrote,
is not part of the site: it is `server/` at the repository's root, a
distribution of its own (FastAPI on Postgres, on Logika's box). Its
`README.md` has the endpoints, the rate limit, the deploy and the
provisioning. `nock share` posts to `https://api.nock.dev/reflections` (the
`endpoints.reflections` setting), the usage reports go to
`https://api.nock.dev/usage` (`endpoints.usage`), and `nock report` to
`https://api.nock.dev/reports` (`endpoints.reports`).
