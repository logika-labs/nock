import os

from nock.steps import Step


def run(step):
    arm, rep = step.value("arm"), int(step.value("rep"))
    if os.environ.get("TOY_FAIL") == arm:
        raise RuntimeError("the detector broke")
    words = (step.unpack() / "words.txt").read_text().split()
    missing = step.metrics()["words"] - len(words)
    detected = missing > 0 and (arm == "toolbox" or rep == 1)
    step.spend(0.1)
    return {"detected": detected, "alarms": int(detected) + (rep == 3)}


Step(snakemake).run(run)
