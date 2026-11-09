"""Release nock.dev to Logika's box: `python3 web/deploy.py HOST`, from a clean checkout.

There is no default host: the box is always named (an SSH destination with sudo, e.g. ops@box-1). The site
is built from the committed tree into `web/build/release/ID` (the tracked files of `site/`, then the pages),
packed, copied over SSH and unpacked as `/srv/sites/nock.dev/releases/ID`; `current`, the link Caddy serves
through, is switched to it in one rename, and the five newest releases are kept. Caddy's site for nock.dev
(`nock.dev.caddy`) is installed as `/etc/caddy/sites/nock.dev.caddy` when it changed, validated with the
box's Caddyfile (the previous one back if Caddy refuses it), and Caddy reloaded. `--rollback` switches
`current` back to the release before it. `--coming-soon` releases the closed site: the coming-soon page as the
home page, beside the legal pages and what they load, so opening the site later is one release without it. The steps are printed first, and nothing runs before the answer
is yes. Standard library only.

    python3 web/deploy.py HOST [--coming-soon | --rollback]
"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from build import build, coming_soon
from publish import DOMAIN, problems

HERE = Path(__file__).resolve().parent
SITES = "/srv/sites"
CADDY_SITES = "/etc/caddy/sites"
CADDY_SITE = HERE / "nock.dev.caddy"
KEEP = 5
# What the closed site keeps: its page, the legal pages and the files they load.
OPEN_WHILE_CLOSED = ("index.html", "style.css", "fonts", "og.jpg", "privacy", "terms")


@dataclass(frozen=True)
class Step:
    what: str
    command: list[str]


def stage(directory: Path) -> None:
    """The site as the committed tree builds it, in `directory`: the tracked files of `site/` (its sheets,
    scripts, fonts and images), then every page. Pages left in `site/` by earlier builds never ship."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "site"],
        cwd=HERE,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for relative in filter(None, tracked.split("\0")):
        target = directory / Path(relative).relative_to("site")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / relative, target)
    build(directory)


def close(directory: Path) -> None:
    """Turn the staged site into the closed one, in place: the coming-soon page at `/`, the legal pages kept,
    everything else (the other pages, the crawler files listing them) removed."""
    for entry in directory.iterdir():
        if entry.name in OPEN_WHILE_CLOSED:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    (directory / "index.html").write_text(coming_soon())


def plan(host: str, release: str, build_directory: Path) -> list[Step]:
    """Every command of a release once it is staged as `build_directory/release`, in order."""
    tarball = build_directory / f"{release}.tar.gz"
    remote = f"/tmp/{DOMAIN}-{release}.tar.gz"
    script = activate(SITES, CADDY_SITES, release, remote, CADDY_SITE.read_text())
    return [
        # macOS tar otherwise adds an AppleDouble `._NAME` beside every file with extended attributes.
        Step(
            "pack the release",
            [
                "env",
                "COPYFILE_DISABLE=1",
                "tar",
                "-C",
                str(build_directory),
                "-czf",
                str(tarball),
                release,
            ],
        ),
        Step(f"copy it to {host}", ["scp", "-q", str(tarball), f"{host}:{remote}"]),
        Step(f"switch {host} to it", ["ssh", host, shlex.join(["sudo", "sh", "-c", script])]),
    ]


def rollback_plan(host: str) -> list[Step]:
    return [
        Step(
            f"switch {host} back", ["ssh", host, shlex.join(["sudo", "sh", "-c", rollback(SITES)])]
        )
    ]


# `current` is replaced by rename(2), which is atomic: a request sees the old release or the new one, never
# neither. Perl does it the same way on Debian (perl-base is essential there) and macOS, which has no `mv -T`.
FLIP = """flip() {
\tln -sfn "releases/$1" "$site/current.new"
\tperl -e 'rename($ARGV[0], $ARGV[1]) or die "rename: $!\\n"' "$site/current.new" "$site/current"
\techo "$site/current -> releases/$1"
}
"""


def activate(sites: str, caddy_sites: str, release: str, tarball: str, caddy_site: str) -> str:
    """The box's side of a release: Caddy's site for nock.dev installed if it changed (and taken back if
    Caddy refuses it), `tarball` (holding the directory `release`) unpacked under `sites`, readable by
    Caddy, `current` switched to it, and the KEEP newest releases kept (names sort by age)."""
    site = shlex.quote(f"{sites}/{DOMAIN}")
    caddy = shlex.quote(f"{caddy_sites}/{DOMAIN}.caddy")
    name, packed = shlex.quote(release), shlex.quote(tarball)
    return f"""set -eu
site={site}
caddy={caddy}
{FLIP}mkdir -p "$site/releases" "$(dirname "$caddy")"
cat > "$caddy.new" <<'CADDY'
{caddy_site}CADDY
if cmp -s "$caddy.new" "$caddy"; then
\trm "$caddy.new"
else
\t[ ! -f "$caddy" ] || cp "$caddy" "$caddy.previous"
\tmv "$caddy.new" "$caddy"
\t# Logika's Caddyfile, which imports the site, reads its placeholders from caddy.env.
\tif ! (set -a; [ ! -f /etc/caddy/caddy.env ] || . /etc/caddy/caddy.env
\t\tcaddy validate --config /etc/caddy/Caddyfile --adapter caddyfile); then
\t\tif [ -f "$caddy.previous" ]; then mv "$caddy.previous" "$caddy"; else rm -f "$caddy"; fi
\t\techo "deploy: Caddy refuses the new site; the previous one is back" >&2
\t\texit 1
\tfi
\trm -f "$caddy.previous"
\tsystemctl reload caddy.service
fi
tar -C "$site/releases" --no-same-owner -xzf {packed}
rm -f {packed}
chmod -R a+rX,go-w "$site/releases/"{name}
flip {name}
ls -1 "$site/releases" | sort -r | tail -n +{KEEP + 1} | while read -r old; do
\t[ "$old" = {name} ] || rm -rf "$site/releases/$old"
done
"""


def rollback(sites: str) -> str:
    """The box's side of a rollback: `current` switched to the release before the one it names."""
    site = shlex.quote(f"{sites}/{DOMAIN}")
    return f"""set -eu
site={site}
{FLIP}now=$(readlink "$site/current")
now=${{now#releases/}}
before=$(ls -1 "$site/releases" | sort -r | awk -v now="$now" 'seen {{ print; exit }} $0 == now {{ seen = 1 }}')
if [ -z "$before" ]; then
\techo "no release before $now is kept" >&2
\texit 1
fi
flip "$before"
"""


def release_id(now: datetime, head: str) -> str:
    """Names sort by age: the box keeps the newest five."""
    return f"{now:%Y%m%dT%H%M%SZ}-{head}"


def destination_problem(host: str) -> str | None:
    """Why HOST cannot be the box: empty, or an option ssh would read."""
    if not host.strip() or host.startswith("-"):
        return "name the box as an SSH destination, e.g. ops@box-1"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deploy.py", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("host", help="the box, as an SSH destination with sudo")
    parser.add_argument(
        "--rollback", action="store_true", help="switch back to the release before the current one"
    )
    parser.add_argument(
        "--coming-soon",
        action="store_true",
        help="release the closed site: the coming-soon page and the legal pages only",
    )
    arguments = parser.parse_args(argv)
    host: str = arguments.host
    if problem := destination_problem(host):
        print(f"deploy: {problem}", file=sys.stderr)
        return 2
    if arguments.rollback:
        steps, what = (
            rollback_plan(host),
            f"Switch {host} back to the release before its current one?",
        )
    else:

        def git(*options: str) -> str:
            return subprocess.run(
                ["git", *options], cwd=HERE.parent, check=True, capture_output=True, text=True
            ).stdout.strip()

        if git("status", "--porcelain"):
            print(
                "deploy: the checkout has uncommitted changes; commit them first", file=sys.stderr
            )
            return 1
        release = release_id(datetime.now(UTC), git("rev-parse", "--short=12", "HEAD"))
        build_directory = HERE / "build" / "release"
        staged = build_directory / release
        stage(staged)
        if found := problems(staged):
            print("deploy: the site is not releasable: " + "; ".join(found), file=sys.stderr)
            return 1
        if arguments.coming_soon:
            close(staged)
            print(
                f"- close it: the coming-soon page at /, only {', '.join(OPEN_WHILE_CLOSED[1:])} beside it"
            )
        steps, what = plan(host, release, build_directory), f"Release {release} to {host}?"
    for step in steps:
        print(f"- {step.what}: {shlex.join(step.command)[:200]}")
    if input(f"{what} [y/N] ").strip().lower() != "y":
        print("deploy: nothing done")
        return 1
    for step in steps:
        print(f"== {step.what}", flush=True)
        if subprocess.run(step.command).returncode != 0:
            print(f"deploy: failed to {step.what}", file=sys.stderr)
            return 1
    print(
        f"switched {host} back" if arguments.rollback else f"released {release} to https://{DOMAIN}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
