import subprocess
import tempfile
from pathlib import Path

from nock.steps import Step


def run(step):
    work = Path(tempfile.mkdtemp())
    words = step.input().read_text().split()
    (work / "words.txt").write_text("\n".join(words) + "\n")
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    step.pack(work)
    return {"words": len(words)}


Step(snakemake).run(run)
