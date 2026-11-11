# nock.dev

The website, kept beside the code it documents. It is not part of nock: `nock
init` vendors `src/nock/` only, and the package is built from `src/` only.
Standard library only, like nock.

```
layout.html        every page's frame: the band and its menu, the main column, the footer
landing/           the landing page and Getting started: their templates (home.html,
                   start.html) and copy.html, the words they share, a block each
legal/             privacy.md and terms.md, each with its plain-words summary (NAME-plain.md)
videos/            the landing page's three videos: their scripts, and the Remotion package, VHS and
                   Playwright recorders that make them from real sessions and the real studio (its README)
site/              style.css, story.js (the landing page's tabs, Getting started's stepper), fonts/, the
                   icons (favicon.svg, favicon-32.png, favicon-16.png, favicon.ico, apple-touch-icon.png),
                   logika.webp and .png (Logika's art, beside "nock in Logika"), videos/ (each video's
                   poster and captions, and Getting started's stills from the review video; the MP4 and
                   WebM are made by videos/ and not committed), og.jpg (the link preview, the
                   owner's art cropped to 1200x630), art/ (each essay's art: NAME.webp, 1600
                   wide, at its top; NAME-480.webp on the list; NAME.jpg, its 1200x630 link
                   preview); the pages, robots.txt, sitemap.xml and
                   the llms files are built into it (gitignored)
build.py           the pages: landing/; the docs from ../src/nock/terms/ (a page per
                   essay, and the reference page with every term); legal/; and
                   what crawlers read: each page's canonical link and JSON-LD, robots.txt,
                   sitemap.xml (each page dated by its sources' last commit), llms.txt and
                   llms-full.txt (every essay, the reference and every term as Markdown)
publish.py         build, and push to GitHub Pages
deploy.py          build, and release to Logika's box (/srv/sites/nock.dev), with nock.dev.caddy,
                   Caddy's site for it there
```

The column, the type scale and the look are the studio's (`src/nock/pages/`).

## Build

```sh
python3 web/build.py
python3 -m http.server -d web/site   # then open http://localhost:8000
```

The docs are nock's own: the guides in `src/nock/terms/guides/` (`nock docs guide.NAME`) and the
short terms beside them (what agents read), so edit those, never `site/`. The guides are a few long
essays, `ESSAYS` in `build.py` in reading order, a page each at `/docs/NAME/` with its art across the
top, a way back to the list beside its title and the next essay as a button at its foot; and the
reference page, `/docs/terms/`, with the guides in `REFERENCE` (every command and exit code) and every
term. The docs index is one list of them, each with its art, title and line. A guide placed nowhere
fails the build. A link between guides lands on the right page.

Each essay's art is the owner's style, drawn through the Codex CLI with the site's art attached as the
house style (as Logika's `banners` tool does), then cut to the three sizes above with ImageMagick:
`magick IN -resize 1600x900^ -gravity center -extent 1600x900 -quality 60 art/NAME.webp`, the same
at 480x270 for the list, and `-resize 1200x675^ -extent 1200x630 -quality 68` for `NAME.jpg`.

**The icons** are a black lowercase n with nock's pink (#ff9ad5) offset up-left and cyan (#8fe9ff)
down-right, no tile: `favicon.svg` is the drawing, and the studio's tab wears the same SVG inline
(`src/nock/pages/studio.html`). The PNGs are rendered from it in Chromium (an `<img>` at the size,
screenshotted with a transparent background): `favicon-32.png` as drawn; `favicon-16.png` from the
same n redrawn on a 16-pixel grid (stems and arch on whole pixels, the colours 1 pixel off), since
the drawing's half-pixel edges blur at 16; `apple-touch-icon.png` (180) with the n at 80% on a white
square of radius 7/32, since iOS puts a transparent icon on black; and
`magick favicon-16.png favicon-32.png favicon.ico`.

**What nock does** is a tab per part (`data-tabs-for`), each its minute of video with the part's words
beside it (`landing/home.html`, the words in `copy.html`); a tab shows its film and pauses the others, and
the address can name one (`/#review`). Getting started is a stepper of seven steps, two of them with a
still from the review video. Without script, every film and every step shows. `site/story.js` does both.

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

## Release to the box

```sh
python3 web/deploy.py ops@box-1              # build from the committed tree, show the steps, ask, release
python3 web/deploy.py ops@box-1 --rollback   # switch back to the release before the current one
```

nock.dev is moving from GitHub Pages to Logika's box, beside api.nock.dev; Pages stays the
fallback until the records point at the box (`deploy/runbooks/sites.md` in Logika's repository has
the switch, and the DNS records it changes). A release stages `site/`'s tracked files, the
built pages and the videos they play (rendered into `site/videos/` by `videos/`, not committed; it refuses
to go while one is missing) in `web/build/release/ID` (so pages left by earlier builds never ship), copies them over
SSH to `/srv/sites/nock.dev/releases/ID`, and switches `current`, the link Caddy serves, in one
rename; the five newest releases stay. It installs `nock.dev.caddy` as
`/etc/caddy/sites/nock.dev.caddy` when it changed, which the box's Caddyfile imports, validates it
with that Caddyfile (the previous one goes back if Caddy refuses it) and reloads Caddy, which then
issues nock.dev's and www.nock.dev's certificates once their records point at the box. Nothing
runs before you answer `y`.

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
