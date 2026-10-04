"""Профили устройств: механические команды и раскладка байта статуса.

MT163 — по документу «MT163 V1.020 communication protocol V1.0» (2017),
MT166 — по «MT166 Communication Protocol V1.1». Сдвиг карты у MT163
в документе отсутствует и восстановлен по обмену демо-программы.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .protocol import encode


@dataclass(frozen=True)
class Param:
    key: str
    title: str
    minimum: int = 0
    maximum: int = 255
    default: int = 0
    choices: tuple[tuple[str, int], ...] = ()

    def check(self, value: int) -> int:
        if self.choices:
            if value not in {v for _, v in self.choices}:
                raise ValueError(f"{self.title}: недопустимое значение {value}")
        elif not self.minimum <= value <= self.maximum:
            raise ValueError(f"{self.title}: нужно от {self.minimum} до {self.maximum}")
        return value


@dataclass(frozen=True)
class Command:
    key: str
    title: str
    cm: int
    pm: int
    params: tuple[Param, ...] = ()
    pack: Callable[[Mapping[str, int]], bytes] | None = None
    timeout: float = 5.0
    documented: bool = True
    note: str = ""

    def data(self, values: Mapping[str, int] | None = None) -> bytes:
        given = dict(values or {})
        resolved = {p.key: p.check(int(given.get(p.key, p.default))) for p in self.params}
        if self.pack:
            return self.pack(resolved)
        return bytes(resolved[p.key] for p in self.params)

    def frame(self, values: Mapping[str, int] | None = None) -> bytes:
        return encode(self.cm, self.pm, self.data(values))


@dataclass(frozen=True)
class Sensor:
    bit: int
    title: str
    on: str = "есть"
    off: str = "нет"
    alarm: bool = False


@dataclass(frozen=True)
class SensorState:
    sensor: Sensor
    on: bool

    @property
    def text(self) -> str:
        return self.sensor.on if self.on else self.sensor.off


@dataclass(frozen=True)
class Profile:
    key: str
    title: str
    baudrate: int
    model: str
    commands: tuple[Command, ...]
    sensors: tuple[Sensor, ...]
    version: Command
    status: Command

    def command(self, key: str) -> Command:
        for command in self.all_commands():
            if command.key == key:
                return command
        raise KeyError(key)

    def find(self, cm: int, pm: int) -> Command | None:
        return next((c for c in self.all_commands() if (c.cm, c.pm) == (cm, pm)), None)

    def all_commands(self) -> tuple[Command, ...]:
        return (self.version, self.status) + self.commands

    def sensor_states(self, value: int) -> list[SensorState]:
        return [SensorState(s, bool(value >> s.bit & 1)) for s in self.sensors]

    def active_sensors(self, value: int) -> list[str]:
        return [state.sensor.title for state in self.sensor_states(value) if state.on]


VERSION = Command("version", "Версия", 0x30, 0x30, timeout=1.0)
STATUS = Command("status", "Статус", 0x32, 0x30, timeout=1.0)

YES_NO = {"on": "да", "off": "нет"}


def _pack_move(values: Mapping[str, int]) -> bytes:
    return bytes((values["direction"] | values["steps"],))


MT163 = Profile(
    key="mt163",
    title="MT163 — картоприёмник",
    baudrate=38400,
    model="MT163",
    version=VERSION,
    status=STATUS,
    commands=(
        Command("eject", "Вернуть карту", 0x31, 0x30),
        Command("retain", "Забрать в бокс", 0x31, 0x33),
        Command(
            "insert_front", "Приём спереди", 0x31, 0x31,
            note="Есть в таблице команд, подробного описания нет.",
        ),
        Command(
            "insert_back", "Приём сзади", 0x31, 0x32,
            note="Есть в таблице команд, подробного описания нет.",
        ),
        Command(
            "move", "Сдвинуть карту", 0x32, 0x33,
            params=(
                Param("direction", "Направление", default=0x00,
                      choices=(("вперёд", 0x00), ("назад", 0x80))),
                Param("steps", "Шагов по 5 мм", minimum=1, maximum=127, default=1),
            ),
            pack=_pack_move,
            documented=False,
            note="Нет в документе, взято из обмена демо-программы MT163VE102K. "
                 "Соответствие направления старшему биту не проверено.",
        ),
        Command(
            "timeout_recovery", "Возврат по таймауту", 0x32, 0x31,
            params=(Param("enabled", "Режим", default=1, choices=(("включить", 1), ("выключить", 0))),),
            timeout=1.0,
        ),
    ),
    sensors=(
        Sensor(6, "Датчик Q3"),
        Sensor(5, "Датчик Q2"),
        Sensor(4, "Датчик Q1"),
        Sensor(3, "Идёт приём карты", **YES_NO),
        Sensor(2, "Идёт возврат карты", **YES_NO),
        Sensor(1, "Ошибка", **YES_NO, alarm=True),
        Sensor(0, "Карта в позиции чтения"),
    ),
)

MT166 = Profile(
    key="mt166",
    title="MT166 — диспенсер",
    baudrate=9600,
    model="MT166",
    version=VERSION,
    status=STATUS,
    commands=(
        Command("to_read", "Выдать в позицию чтения", 0x31, 0x30),
        Command("to_bezel", "Выдать к окну", 0x31, 0x31),
        Command("to_outside", "Выдать наружу", 0x31, 0x32),
        Command("collect", "Забрать в коллектор", 0x33, 0x30),
    ),
    sensors=(
        Sensor(7, "Накопитель пуст", **YES_NO, alarm=True),
        Sensor(6, "Карта у окна"),
        Sensor(5, "Карта в позиции чтения"),
        Sensor(4, "Карт мало", **YES_NO, alarm=True),
        Sensor(3, "Идёт выдача", **YES_NO),
        Sensor(2, "Идёт сбор", **YES_NO),
        Sensor(1, "Ошибка выдачи", **YES_NO, alarm=True),
        Sensor(0, "Возврат по таймауту", on="поддерживается", off="нет"),
    ),
)

PROFILES = {profile.key: profile for profile in (MT163, MT166)}


def detect(version: str) -> Profile | None:
    text = version.upper()
    return next((p for p in PROFILES.values() if p.model in text), None)
