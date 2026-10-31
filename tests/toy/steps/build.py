def run(step):
    words = step.file("corpus").read_text().split()
    (step.directory / "words.txt").write_text("\n".join(words) + "\n")
    return {"words": len(words)}
