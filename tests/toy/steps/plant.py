import json


def run(step):
    bug = json.loads(step.file("bug").read_text())
    words = (step.directory / "words.txt").read_text().split()
    kept = [word for word in words if word != bug["drop"]]
    (step.directory / "words.txt").write_text("\n".join(kept) + "\n")
    return {"dropped": len(words) - len(kept)}
