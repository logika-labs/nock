from nock.steps import Step


def run(step):
    work = step.unpack("state")
    words = (work / "words.txt").read_text().split()
    (work / "words.txt").write_text("\n".join(sorted([*words, "banana"])) + "\n")
    step.pack(work)
    return {"fixed": True}


Step(snakemake).run(run)
