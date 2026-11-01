from nock.steps import Step


def run(step):
    control, toolbox = step.metrics("control"), step.metrics("toolbox")
    return {
        "gain": int(bool(toolbox.get("detected"))) - int(bool(control.get("detected"))),
        "fixed": bool(step.snakemake.input.fix),
    }


Step(snakemake).run(run)
