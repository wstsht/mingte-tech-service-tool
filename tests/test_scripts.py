import threading
from datetime import datetime

import pytest

from mtservice.devices import MT163, MT166
from mtservice.emulator import Emulator
from mtservice.link import Exchange
from mtservice.scripts import (
    CommandStep,
    PauseStep,
    RepeatStep,
    Runner,
    Script,
    WaitStep,
    check,
    describe,
    from_json,
    to_json,
)


def direct(device: Emulator):
    def call(frame: bytes, timeout: float) -> Exchange:
        device.write(frame)
        data = device.read(0.5)
        return Exchange(
            request=frame,
            response=data or None,
            source="script",
            started=datetime.now(),
            elapsed=0.0,
            error=None if data else "нет ответа",
        )

    return call


class Recorder:
    def __init__(self):
        self.started = []
        self.failed = []
        self.stats = []

    def step_started(self, path):
        self.started.append(path)

    def step_failed(self, path, message):
        self.failed.append((path, message))

    def stats_changed(self, stats):
        self.stats.append(stats)


def sample() -> Script:
    return Script(
        profile="mt163",
        stop_on_error=False,
        steps=[
            RepeatStep(
                times=3,
                steps=[
                    CommandStep("insert_front"),
                    WaitStep(bit=0, state=True, timeout_ms=1000),
                    CommandStep("timeout_recovery", {"enabled": 0}),
                    PauseStep(ms=0),
                    CommandStep("retain"),
                ],
            ),
        ],
    )


def test_json_round_trip():
    script = sample()
    assert from_json(to_json(script)) == script


def test_json_with_unknown_step_is_rejected():
    with pytest.raises(ValueError):
        from_json('{"profile": "mt163", "steps": [{"type": "jump"}]}')


def test_json_with_broken_syntax_is_rejected():
    with pytest.raises(ValueError):
        from_json("{")


def test_describe_steps():
    assert describe(CommandStep("eject"), MT163) == "Вернуть карту"
    assert describe(CommandStep("timeout_recovery", {"enabled": 0}), MT163) == (
        "Возврат по таймауту: выключить"
    )
    assert describe(PauseStep(ms=750), MT163) == "Пауза 750 мс"
    assert describe(RepeatStep(times=5), MT163) == "Повторить 5 раз"
    assert describe(RepeatStep(times=0), MT163) == "Повторять без конца"
    assert describe(WaitStep(bit=4, state=True, timeout_ms=3000), MT163) == (
        "Ждать «Датчик Q1» = Да, не дольше 3 с"
    )
    assert describe(CommandStep("teleport"), MT163) == "Неизвестная команда teleport"


def test_check_reports_problems():
    script = Script(
        profile="mt163",
        steps=[
            CommandStep("to_bezel"),
            CommandStep("timeout_recovery", {"enabled": 7}),
            WaitStep(bit=7),
            RepeatStep(times=0),
            PauseStep(ms=-1),
        ],
    )
    problems = check(script, MT163)
    assert len(problems) == 5
    assert check(sample(), MT163) == []


def test_runner_repeats_and_counts():
    device = Emulator(MT163)
    recorder = Recorder()
    runner = Runner(sample(), MT163, direct(device), recorder)
    assert runner.run() == "done"
    assert device.state.retained == 3
    assert runner.stats.iterations == 3
    assert runner.stats.commands == 9
    assert runner.stats.failures == 0
    assert recorder.started[:3] == [(0,), (0, 0), (0, 1)]


def test_runner_stops_on_first_error():
    device = Emulator(MT163)
    script = Script("mt163", [CommandStep("eject"), CommandStep("insert_front")], stop_on_error=True)
    recorder = Recorder()
    runner = Runner(script, MT163, direct(device), recorder)
    assert runner.run() == "failed"
    assert runner.stats.failures == 1
    assert device.state.card is None
    assert recorder.failed == [((0,), "отказ")]


def test_runner_can_keep_going_after_errors():
    device = Emulator(MT163)
    script = Script("mt163", [CommandStep("eject"), CommandStep("insert_front")], stop_on_error=False)
    runner = Runner(script, MT163, direct(device))
    assert runner.run() == "done"
    assert runner.stats.failures == 1
    assert device.state.card == "read"


def test_wait_times_out():
    script = Script("mt163", [WaitStep(bit=0, state=True, timeout_ms=100)])
    recorder = Recorder()
    runner = Runner(script, MT163, direct(Emulator(MT163)), recorder, poll_interval=0.01)
    assert runner.run() == "failed"
    assert "не дождались" in recorder.failed[0][1]


def test_wait_for_mt166_bezel():
    script = Script("mt166", [CommandStep("to_bezel"), WaitStep(bit=6, state=True, timeout_ms=500)])
    assert Runner(script, MT166, direct(Emulator(MT166))).run() == "done"


def test_stop_interrupts_endless_loop():
    script = Script("mt163", [RepeatStep(times=0, steps=[PauseStep(ms=10)])])
    runner = Runner(script, MT163, direct(Emulator(MT163)))
    threading.Timer(0.1, runner.stop).start()
    assert runner.run() == "stopped"
    assert runner.stats.iterations > 0


def test_runner_refuses_invalid_script():
    script = Script("mt163", [CommandStep("to_bezel")])
    recorder = Recorder()
    assert Runner(script, MT163, direct(Emulator(MT163)), recorder).run() == "failed"
    assert recorder.failed
