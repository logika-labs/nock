import os


def run(step):
    if os.environ.get("TOY_FAIL") == step.value("arm"):
        raise RuntimeError("the detector broke")
    words = (step.directory / "words.txt").read_text().split()
    missing = step.results("build")["words"] - len(words)
    detected = missing > 0 and (step.value("arm") == "toolbox" or step.value("rep") == 1)
    (step.directory / "report.md").write_text(f"missing: {missing}\n")
    step.spend(0.1)
    return {"detected": detected, "alarms": int(detected) + (step.value("rep") == 3)}
