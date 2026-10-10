from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Union

from .devices import Profile
from .link import Exchange
from .protocol import OK, status_text


@dataclass
class CommandStep:
    command: str
    values: dict[str, int] = field(default_factory=dict)


@dataclass
class PauseStep:
    ms: int = 500


@dataclass
class RepeatStep:
    times: int = 2  # 0 — без конца
    steps: list[Step] = field(default_factory=list)


@dataclass
class WaitStep:
    bit: int
    state: bool = True
    timeout_ms: int = 10_000


Step = Union[CommandStep, PauseStep, RepeatStep, WaitStep]


@dataclass
class Script:
    profile: str
    steps: list[Step] = field(default_factory=list)
    stop_on_error: bool = True


def _step_to_dict(step: Step) -> dict:
    if isinstance(step, CommandStep):
        return {"type": "command", "command": step.command, "values": dict(step.values)}
    if isinstance(step, PauseStep):
        return {"type": "pause", "ms": step.ms}
    if isinstance(step, RepeatStep):
        return {"type": "repeat", "times": step.times, "steps": [_step_to_dict(s) for s in step.steps]}
    if isinstance(step, WaitStep):
        return {"type": "wait", "bit": step.bit, "state": step.state, "timeout_ms": step.timeout_ms}
    raise TypeError(step)


def _step_from_dict(data: dict) -> Step:
    kind = data.get("type")
    if kind == "command":
        values = {str(k): int(v) for k, v in data.get("values", {}).items()}
        return CommandStep(str(data["command"]), values)
    if kind == "pause":
        return PauseStep(int(data["ms"]))
    if kind == "repeat":
        return RepeatStep(int(data["times"]), [_step_from_dict(s) for s in data.get("steps", [])])
    if kind == "wait":
        return WaitStep(int(data["bit"]), bool(data.get("state", True)), int(data.get("timeout_ms", 10_000)))
    raise ValueError(f"неизвестный тип шага: {kind!r}")


def to_json(script: Script) -> str:
    data = {
        "profile": script.profile,
        "stop_on_error": script.stop_on_error,
        "steps": [_step_to_dict(s) for s in script.steps],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def from_json(text: str) -> Script:
    try:
        data = json.loads(text)
        return Script(
            profile=str(data["profile"]),
            steps=[_step_from_dict(s) for s in data.get("steps", [])],
            stop_on_error=bool(data.get("stop_on_error", True)),
        )
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"файл сценария повреждён: {exc}") from exc


def describe(step: Step, profile: Profile) -> str:
    if isinstance(step, CommandStep):
        try:
            command = profile.command(step.command)
        except KeyError:
            return f"Неизвестная команда {step.command}"
        parts = []
        for param in command.params:
            value = step.values.get(param.key, param.default)
            label = next((name for name, v in param.choices if v == value), str(value))
            parts.append(label)
        return f"{command.title}: {', '.join(parts)}" if parts else command.title
    if isinstance(step, PauseStep):
        return f"Пауза {step.ms} мс"
    if isinstance(step, RepeatStep):
        return f"Повторить {step.times} раз" if step.times else "Повторять без конца"
    if isinstance(step, WaitStep):
        sensor = next((s for s in profile.sensors if s.bit == step.bit), None)
        title = sensor.title if sensor else f"бит {step.bit}"
        state = (sensor.on if step.state else sensor.off) if sensor else int(step.state)
        return f"Ждать «{title}» = {state}, не дольше {step.timeout_ms / 1000:g} с"
    raise TypeError(step)


def check(script: Script, profile: Profile) -> list[str]:
    problems: list[str] = []

    def visit(steps: list[Step], prefix: str) -> None:
        for number, step in enumerate(steps, 1):
            where = f"шаг {prefix}{number}"
            if isinstance(step, CommandStep):
                try:
                    profile.command(step.command).data(step.values)
                except KeyError:
                    problems.append(f"{where}: у {profile.model} нет команды {step.command}")
                except ValueError as exc:
                    problems.append(f"{where}: {exc}")
            elif isinstance(step, PauseStep):
                if step.ms < 0:
                    problems.append(f"{where}: пауза не может быть отрицательной")
            elif isinstance(step, WaitStep):
                if step.bit not in {s.bit for s in profile.sensors}:
                    problems.append(f"{where}: у {profile.model} нет датчика на бите {step.bit}")
                if step.timeout_ms <= 0:
                    problems.append(f"{where}: нужен положительный таймаут")
            elif isinstance(step, RepeatStep):
                if step.times < 0:
                    problems.append(f"{where}: число повторов не может быть отрицательным")
                if not step.steps:
                    problems.append(f"{where}: пустой цикл")
                visit(step.steps, f"{prefix}{number}.")

    visit(script.steps, "")
    return problems


@dataclass
class RunStats:
    commands: int = 0
    failures: int = 0
    iterations: int = 0
    started: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started


class Listener:
    def step_started(self, path: tuple[int, ...]) -> None:
        pass

    def step_failed(self, path: tuple[int, ...], message: str) -> None:
        pass

    def stats_changed(self, stats: RunStats) -> None:
        pass


class _Stopped(Exception):
    pass


class _Failed(Exception):
    pass


class Runner:
    def __init__(
        self,
        script: Script,
        profile: Profile,
        call: Callable[[bytes, float], Exchange],
        listener: Listener | None = None,
        poll_interval: float = 0.1,
    ) -> None:
        self.script = script
        self.profile = profile
        self.stats = RunStats()
        self._call = call
        self._listener = listener or Listener()
        self._poll_interval = poll_interval
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> str:
        self.stats = RunStats()
        problems = check(self.script, self.profile)
        if problems:
            for problem in problems:
                self._listener.step_failed((), problem)
            return "failed"
        try:
            self._run_steps(self.script.steps, ())
        except _Stopped:
            return "stopped"
        except _Failed:
            return "failed"
        finally:
            self._listener.stats_changed(self.stats)
        return "done"

    def _run_steps(self, steps: list[Step], prefix: tuple[int, ...]) -> None:
        for index, step in enumerate(steps):
            if self._stop.is_set():
                raise _Stopped
            path = prefix + (index,)
            self._listener.step_started(path)
            if isinstance(step, CommandStep):
                self._run_command(step, path)
            elif isinstance(step, PauseStep):
                self._sleep(step.ms / 1000)
            elif isinstance(step, WaitStep):
                self._wait(step, path)
            elif isinstance(step, RepeatStep):
                self._repeat(step, path)

    def _repeat(self, step: RepeatStep, path: tuple[int, ...]) -> None:
        done = 0
        while step.times == 0 or done < step.times:
            self._run_steps(step.steps, path)
            done += 1
            if len(path) == 1:
                self.stats.iterations += 1
                self._listener.stats_changed(self.stats)

    def _run_command(self, step: CommandStep, path: tuple[int, ...]) -> None:
        command = self.profile.command(step.command)
        exchange = self._call(command.frame(step.values), command.timeout)
        self.stats.commands += 1
        if not exchange.ok:
            self._fail(path, exchange.error or "нет ответа")
        elif exchange.reply.status != OK:
            self._fail(path, status_text(exchange.reply.status))
        self._listener.stats_changed(self.stats)

    def _wait(self, step: WaitStep, path: tuple[int, ...]) -> None:
        deadline = time.monotonic() + step.timeout_ms / 1000
        status = self.profile.status
        while True:
            exchange = self._call(status.frame(), status.timeout)
            if exchange.ok and bool(exchange.reply.status >> step.bit & 1) == step.state:
                return
            if time.monotonic() >= deadline:
                self._fail(path, f"не дождались: {describe(step, self.profile)}")
                return
            self._sleep(self._poll_interval)

    def _sleep(self, seconds: float) -> None:
        if self._stop.wait(seconds):
            raise _Stopped

    def _fail(self, path: tuple[int, ...], message: str) -> None:
        self.stats.failures += 1
        self._listener.step_failed(path, message)
        if self.script.stop_on_error:
            raise _Failed
