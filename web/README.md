# nock.dev

The website, kept beside the code it documents. It is not part of nock: `nock
init` vendors `src/nock/` only, and the package is built from `src/` only.
Standard library only, like nock.

```
layout.html        every page's frame: the band and its menu, the main column, the footer
landing/           the landing page, About and Getting started: their templates (home.html,
                   about.html, start.html) and copy.html, the words they share, a block each
legal/             privacy.md and terms.md, each with its plain-words summary (NAME-plain.md)
site/              style.css, demo.js and demo.css (the demo), fonts/, og.jpg (the link preview,
                   the owner's art cropped to 1200x630); the pages are built into
                   it (gitignored), and studio/topics.css, the studio's sheet, copied in
build.py           the pages: landing/; the docs from ../src/nock/terms/ (a page per
                   guide, in four groups, with the terms an agent reads on it); legal/; and
                   what crawlers read: each page's canonical link and JSON-LD, robots.txt,
                   sitemap.xml (each page dated by its sources' last commit), llms.txt and
                   llms-full.txt (every guide and term as Markdown)
publish.py         build, and push to GitHub Pages
```

The column, the type scale and the look are the studio's (`src/nock/pages/`).

## Build

```sh
python3 web/build.py
python3 -m http.server -d web/site   # then open http://localhost:8000
```

The docs are nock's own: the guides in `src/nock/terms/guides/` (a page each, `nock docs
guide.NAME`) and the short terms beside them (what agents read), so edit those, never `site/`.
`PAGES` in `build.py` places each guide in a group (Start, Every day, Extending, Reference) with
the terms folded under it as "What your agent reads"; the terms page lists every term. A guide
placed nowhere, or a term that does not exist, fails the build. A link between guides lands on the
right page, and an old address, `/docs/#ANCHOR`, is sent on to the page that has the heading now.

**The demo** (`site/demo.js`) is coded, not recorded: three scenes,
each a script of steps with a caption, every element saying from which step it shows (`data-at`,
`data-until`) and which classes it takes (`data-on`). The landing page places it on one stage with
a tab per scene (`data-tabs-for`) that plays in view, and Getting started shows a step of it as a
still (`data-demo-still`); with reduced motion nothing plays by itself.

The legal pages carry the TL;DR switch at the right end of the title's line. They show only their
summary while it is on (the default) and only the full text while it is off; without script, both. Turning it off is kept in the visitor's
browser's `localStorage`, as the privacy policy says.

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
