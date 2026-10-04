from pathlib import Path

import pytest

from mtservice.devices import PROFILES
from mtservice.emulator import Emulator
from mtservice.link import Link
from mtservice.scripts import PauseStep, RepeatStep, Runner, check, from_json

EXAMPLES = sorted((Path(__file__).parent.parent / "examples").glob("*.json"))


def test_examples_exist():
    assert EXAMPLES


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_runs_on_emulator(path):
    script = from_json(path.read_text(encoding="utf-8"))
    profile = PROFILES[script.profile]
    assert check(script, profile) == []

    def speed_up(steps):
        for step in steps:
            if isinstance(step, RepeatStep):
                step.times = 2
                speed_up(step.steps)
            elif isinstance(step, PauseStep):
                step.ms = 0

    speed_up(script.steps)
    link = Link(Emulator(profile), gap=0)
    link.start()
    try:
        runner = Runner(script, profile, lambda frame, timeout: link.call(frame, timeout, "script"))
        assert runner.run() == "done"
        assert runner.stats.failures == 0
    finally:
        link.close()
