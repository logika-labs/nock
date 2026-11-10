"""Stills of the real studio at 2x, for the videos: `nock studio` serving the demo repository (never the
owner's own studio), driven by Playwright as the owner would use it. Each step opens the page, does
what it says (clicks, typing), saves the viewport as public/shots/NAME.png, and the boxes of the
elements it names as NAME.json, which the compositions point and ring at.

    uv run --with playwright python record/shots.py STUDIO_URL STEPS.json [NAME…]

STEPS: [{"name": …, "hash": "#topics/charge-sweep", "actions": [["click", SELECTOR], ["type", TEXT],
         ["key", KEY], ["wait", MS], ["scroll", SELECTOR]], "boxes": {"label": SELECTOR}}]
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SHOTS = Path(__file__).resolve().parent.parent / "public" / "shots"
# The still's CSS size: 1440 wide, as tall as a 1600x836 card shows at 1440/1600.
VIEWPORT = {"width": 1440, "height": 752}


def act(page, action: list) -> None:
    kind, *rest = action
    if kind == "click":
        page.locator(rest[0]).first.click()
        page.wait_for_timeout(700)
    elif kind == "type":
        page.keyboard.type(rest[0], delay=8)
        page.wait_for_timeout(300)
    elif kind == "key":
        page.keyboard.press(rest[0])
        page.wait_for_timeout(700)
    elif kind == "wait":
        page.wait_for_timeout(int(rest[0]))
    elif kind == "scroll":
        page.locator(rest[0]).first.evaluate("element => element.scrollIntoView({block: 'center'})")
        page.wait_for_timeout(500)
    elif kind == "until":
        page.locator(rest[0]).first.wait_for(timeout=int(rest[1]) if len(rest) > 1 else 600_000)
        page.wait_for_timeout(800)
    elif kind == "top":
        page.evaluate(f"window.scrollTo(0, {int(rest[0])})")
        page.wait_for_timeout(400)


def main(url: str, steps_path: str, *names: str) -> int:
    steps = json.loads(Path(steps_path).read_text())
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for step in steps:
            if names and step["name"] not in names:
                continue
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
            page.goto(url + step.get("hash", ""))
            page.wait_for_timeout(1500)
            for action in step.get("actions", []):
                act(page, action)
            page.wait_for_timeout(600)
            boxes = {}
            for label, selector in step.get("boxes", {}).items():
                found = page.locator(selector)
                box = found.first.bounding_box() if found.count() else None
                boxes[label] = box
            page.screenshot(path=SHOTS / f"{step['name']}.png")
            (SHOTS / f"{step['name']}.json").write_text(json.dumps(boxes, indent=2))
            print(
                step["name"],
                {
                    label: box and {k: round(v) for k, v in box.items()}
                    for label, box in boxes.items()
                },
            )
            page.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
