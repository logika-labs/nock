# nock.dev

The website, kept beside the code it documents. It is not part of nock: `nock
init` vendors `src/nock/` only, and the package is built from `src/` only.
Standard library only, like nock.

```
site/              the pages: index.html, style.css, docs/ (built, gitignored)
docs.html          the docs page's template
legal/             privacy.md and terms.md → site/privacy/, site/terms/ (built, gitignored)
page.html          their template
build.py           ../README.md → site/docs/index.html, with a table of contents; legal/ → its pages
publish.py         build, and push to GitHub Pages
```

## Build

```sh
python3 web/build.py
```

The docs page is the README, so edit the README, never `site/docs/`. To look at
the site, serve `web/site/` (`python3 -m http.server -d web/site`).

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
