"""Writes public/data/NAME.json, what a composition shows: the recordings it plays (with their lengths,
read by ffprobe), the studio's stills, and for the reflection video the demo's own telemetry (the
sessions before the round and the shell commands each ran) and the tool the round wrote, and for the
evaluation video what the eval's agents answered.

    python3 record/prepare.py reflection DEMO
    python3 record/prepare.py review DEMO
    python3 record/prepare.py evaluation DEMO
"""

import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PUBLIC = HERE / "public"
# A command that is part of finding a failing test by hand; nock's own calls (the primer's topics
# list) are not.
DIGGING = re.compile(r"\b(pytest|tail|grep|head|sed|git show|git log|git diff)\b")


def seconds(clip: str) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(PUBLIC / clip),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout)


def clip(name: str, label: str, start: float = 0, until: float | None = None) -> dict:
    """A recording, played from START to UNTIL (its end by default)."""
    return {
        "clip": f"clips/{name}.mp4",
        "seconds": until or seconds(f"clips/{name}.mp4"),
        "from": start,
        "label": label,
    }


def commands(line: str) -> list[str]:
    """The programs a shell line runs: `pytest -q | tail -40; grep x f` is three."""
    found = []
    for statement in re.split(r"&&|;", line):
        if ".nock/nock topics" in statement:
            continue
        found += [part.strip() for part in re.split(r"\|\||\|", statement) if DIGGING.search(part)]
    return found


def local(moment: str) -> str:
    return (
        datetime.fromisoformat(moment.replace("Z", "+00:00")).astimezone().strftime("%b %d · %H:%M")
    )


def reflection(demo: Path) -> dict:
    database = sqlite3.connect(demo / ".nock/local/nock.db")
    rows, counts = [], []
    sessions = database.execute(
        "SELECT id, started, title FROM sessions WHERE role = 'interactive' ORDER BY started"
    ).fetchall()
    for session, started, title in sessions:
        prompt = database.execute(
            "SELECT text FROM prompts WHERE session = ? ORDER BY moment", (session,)
        ).fetchone()
        if not prompt or "pytest" not in prompt[0]:
            continue
        calls = []
        count = 0
        for (line,) in database.execute(
            "SELECT input FROM events WHERE session = ? AND tool = 'Bash' ORDER BY moment",
            (session,),
        ):
            found = commands(line)
            count += len(found)
            for command in found:
                shape = (
                    "pytest"
                    if "pytest" in command
                    else command.split()[0]
                    if not command.startswith("git ")
                    else " ".join(command.split()[:2])
                )
                calls.append({"shape": shape, "command": command[:64]})
        counts.append(count)
        rows.append({"started": local(started), "title": title, "calls": calls})
    before = rows[:5]
    tool = (demo / ".nock/tools/tests.py").read_text().splitlines()
    return {
        "opening": clip("s1", "claude · ~/demo/tally"),
        "sessions": [clip("s2", "session 2"), clip("s3", "session 3"), clip("s4", "session 4")],
        "ledger": {
            "database": ".nock/local/nock.db · every session's tool calls",
            "rows": before,
            "repeated": ["pytest", "tail", "grep", "head", "git show"],
        },
        "round": clip("round", "claude · /nock-reflect"),
        "tool": {
            "path": ".nock/tools/tests.py · the round's new command",
            "code": "\n".join(tool[:34]),
        },
        "next": clip("s5", "claude · the next session"),
        "counter": {
            "before": counts[0],
            "after": 1,
            "unit": "session 1's commands → one failures call",
        },
        "cards": [
            {
                "shot": f"shots/{name}.png",
                "from": view(),
                "to": view(boxes(name)["item"], 1.3),
                "label": label,
            }
            for name, label in [
                ("round-add", "new"),
                ("round-retire", "retired"),
                ("round-flag", "sharpened"),
            ]
        ],
    }


WIDTH, HEIGHT, FULL = 1440, 752, 1600 / 1440


def boxes(name: str) -> dict:
    return json.loads((PUBLIC / "shots" / f"{name}.json").read_text())


def view(box: dict | None = None, scale: float = FULL) -> dict:
    """The view of a still that centres BOX at SCALE (the whole still at FULL)."""
    if box is None or scale <= FULL:
        return {"x": 0, "y": 0, "scale": FULL}
    seen_width, seen_height = 1600 / scale, 836 / scale
    x = box["x"] + box["width"] / 2 - seen_width / 2
    y = box["y"] + box["height"] / 2 - seen_height / 2
    return {
        "x": round(min(max(x, 0), WIDTH - seen_width)),
        "y": round(min(max(y, 0), HEIGHT - seen_height)),
        "scale": scale,
    }


def shot(
    name: str,
    seconds: float,
    zoom: str | None = None,
    scale: float = 1.35,
    ring: str | None = None,
    press: str | None = None,
    begin: str | None = None,
    begin_scale: float = 1.35,
) -> dict:
    found = boxes(name)
    out = {
        "shot": f"shots/{name}.png",
        "seconds": seconds,
        "from": view(found.get(begin), begin_scale) if begin else view(),
        "to": view(found.get(zoom), scale) if zoom else view(),
    }
    frames = round(seconds * 30)
    if ring and found.get(ring):
        box = found[ring]
        out["ring"] = {
            "x": box["x"],
            "y": box["y"],
            "width": box["width"],
            "height": box["height"],
            "start": round(frames * 0.3),
        }
    if press and found.get(press):
        box = found[press]
        target = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        out["pointer"] = [
            [target[0] + 220, target[1] + 160, 0],
            [target[0] + 220, target[1] + 160, 6],
            [target[0], target[1], round(frames * 0.55)],
        ]
        out["press"] = round(frames * 0.6)
    return out


def review(demo: Path) -> dict:
    return {
        "opening": clip("v1", "claude · ~/demo/tally"),
        "consult": clip("v7", "claude · a new session, later", until=82),
        "beats": [
            [
                shot("review-list", 2.5, zoom="topic", scale=1.3, ring="topic"),
                shot("review-open", 3.5, zoom="decision", ring="decision"),
            ],
            [
                shot("review-fill1", 2.6, zoom="text", scale=1.3, ring="text"),
                shot("review-fill2", 2.7, zoom="image", scale=1.3, ring="image"),
                shot("review-fill3", 2.7, zoom="video", scale=1.3, ring="video"),
            ],
            [
                shot("review-options", 3.2, press="star"),
                shot("review-starred", 2.6, zoom="star", scale=1.5),
                shot("review-compare", 4.2),
            ],
            [
                shot("review-ask", 2.2, zoom="box", scale=1.45),
                shot("review-asked", 1.8),
                shot("review-commented", 2.0),
                shot("review-address", 2.2, press="address"),
                shot("review-answer", 2.0),
                shot("review-v2", 1.8),
            ],
            [
                shot("review-accept-before", 2.4, press="accept"),
                shot("review-accepted", 1.8, zoom="mark", scale=1.6),
                shot("review-reject-before", 2.2, press="reject"),
                shot("review-rejected", 1.6, ring="card"),
                shot("review-done", 2.0, zoom="topic", scale=1.3, ring="topic"),
            ],
        ],
    }


def evaluation(demo: Path) -> dict:
    """The eval in the demo (evals/fix): three of its agents' answers to one bug, the recordings and the
    stills, the Experiment tab's of the demo and of Logika's own evaluation (its studio on another port)."""
    scenario = demo / "evals" / "fix"
    bug = "tax-rounding"
    answers = [
        {
            "label": f"{model} · run {rep}",
            "text": (
                scenario
                / "results"
                / "fixed"
                / f"model={model}"
                / f"bug={bug}"
                / f"rep={rep}"
                / "answer.txt"
            )
            .read_text()
            .strip(),
        }
        for model, rep in (("haiku", 1), ("haiku", 2), ("sonnet", 1))
    ]
    complaint = json.loads((scenario / "parameters" / "bug" / f"{bug}.json").read_text())[
        "complaint"
    ]
    return {
        "complaint": complaint,
        "answers": answers,
        "fan": [shot("eval-tree", 6, zoom="fix", scale=1.3, ring="fix")],
        "logika": [
            shot(
                "eval-logika",
                8,
                zoom="instrument",
                scale=1.7,
                ring="instrument",
                begin="window",
                begin_scale=1.3,
            )
        ],
        "stages": [
            shot("eval-whole", 5.5, zoom="score", scale=2.3, begin="app", begin_scale=2.3),
            shot("eval-whole", 2.5, zoom="window", scale=1.3, begin="score", begin_scale=2.3),
        ],
        "decisions": [
            shot(
                "eval-whole",
                3.5,
                zoom="fixed",
                scale=2.2,
                ring="fixed",
                begin="window",
                begin_scale=1.3,
            ),
            shot("eval-measures", 3.5, zoom="measures", scale=1.3, ring="measures"),
        ],
        "runs": [
            clip("e-run", "tally · nock eval run"),
            clip("e-rerun", "tally · the scoring changed"),
        ],
        "drill": [
            shot("eval-run", 2.4, press="fix"),
            shot("eval-answer", 2.4, zoom="answer", scale=1.45, ring="answer"),
            shot("eval-follow", 2.2, ring="following"),
        ],
        "ask": clip("e-ask", "claude · tally", start=14, until=57),
    }


def main(name: str, demo: str) -> int:
    data = {"reflection": reflection, "review": review, "evaluation": evaluation}[name](
        Path(demo).expanduser()
    )
    (PUBLIC / "data").mkdir(parents=True, exist_ok=True)
    (PUBLIC / "data" / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
