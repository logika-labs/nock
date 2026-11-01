import json

from nock.steps import Step


def run(step):
    bug = json.loads(step.input("bug").read_text())
    work = step.unpack("state")
    words = (work / "words.txt").read_text().split()
    kept = [word for word in words if word != bug["drop"]]
    (work / "words.txt").write_text("\n".join(kept) + "\n")
    step.pack(work)
    return {"dropped": len(words) - len(kept), "words": len(words)}


Step(snakemake).run(run)
