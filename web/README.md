# nock.dev

The website, kept beside the code it documents. It is not part of nock: `nock
init` vendors `src/nock/` only, and the package is built from `src/` only.
Standard library only, like nock.

```
site/              the pages: index.html, style.css, docs/ (built, gitignored)
docs.html          the docs page's template
build.py           ../README.md → site/docs/index.html, with a table of contents
publish.py         build, and push to GitHub Pages
api/               api.nock.dev, where `nock share` sends a summary (not deployed)
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

`api/reflections.py` is api.nock.dev: `POST /reflections` keeps a summary in
SQLite and answers with its id; `GET /health`. It is not deployed. To run it:

- `python3 reflections.py --database /srv/nock-api/reflections.db --port 8610`,
  as the systemd unit `api/nock-api.service` does (code in `/srv/nock-api/`,
  restart on failure). It listens on 127.0.0.1 only.
- A TLS proxy for `api.nock.dev` in front of it, forwarding to
  `127.0.0.1:8610` with `Host` kept, request bodies at most 128 KB, and a rate
  limit per client address of 6 requests a minute with a burst of 5, answering
  429 beyond it.
- DNS for `api.nock.dev` pointing at the box. `nock share` posts to
  `https://api.nock.dev/reflections` (the `share.endpoint` setting).
