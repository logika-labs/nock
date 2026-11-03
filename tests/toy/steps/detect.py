import os

from nock.steps import Step


def run(step):
    arm, rep = step.value("arm"), int(step.value("rep"))
    if os.environ.get("TOY_FAIL") == arm:
        (step.directory / "attempt.txt").write_text("half done\n")
        raise RuntimeError("the detector broke")
    words = (step.unpack() / "words.txt").read_text().split()
    missing = step.metrics()["words"] - len(words)
    detected = missing > 0 and (arm == "toolbox" or rep == 1)
    step.spend(0.1, tokens=100)
    found = {"detected": detected, "alarms": int(detected) + (rep == 3)}
    if step.previous is not None:
        found["resumed"] = (step.previous / "attempt.txt").is_file()
    return found


Step(snakemake).run(run)
