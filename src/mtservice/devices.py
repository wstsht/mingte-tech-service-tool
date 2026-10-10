from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .protocol import encode


@dataclass(frozen=True)
class Param:
    key: str
    title: str
    choices: tuple[tuple[str, int], ...]
    default: int

    def check(self, value: int) -> int:
        if value not in {v for _, v in self.choices}:
            raise ValueError(f"{self.title}: недопустимое значение {value}")
        return value


@dataclass(frozen=True)
class Command:
    key: str
    title: str
    cm: int
    pm: int
    params: tuple[Param, ...] = ()
    timeout: float = 5.0

    def data(self, values: Mapping[str, int] | None = None) -> bytes:
        given = dict(values or {})
        return bytes(p.check(int(given.get(p.key, p.default))) for p in self.params)

    def frame(self, values: Mapping[str, int] | None = None) -> bytes:
        return encode(self.cm, self.pm, self.data(values))


@dataclass(frozen=True)
class Sensor:
    bit: int
    title: str
    alarm: bool = False
    on: str = "Да"
    off: str = "Нет"


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
    full_version: Command | None = None

    def command(self, key: str) -> Command:
        for command in self.all_commands():
            if command.key == key:
                return command
        raise KeyError(key)

    def find(self, cm: int, pm: int) -> Command | None:
        return next((c for c in self.all_commands() if (c.cm, c.pm) == (cm, pm)), None)

    def all_commands(self) -> tuple[Command, ...]:
        extra = (self.full_version,) if self.full_version else ()
        return (self.version, self.status) + extra + self.commands

    def sensor_states(self, value: int) -> list[SensorState]:
        return [SensorState(s, bool(value >> s.bit & 1)) for s in self.sensors]

    def active_sensors(self, value: int) -> list[str]:
        return [state.sensor.title for state in self.sensor_states(value) if state.on]


VERSION = Command("version", "Версия", 0x30, 0x30, timeout=1.0)
STATUS = Command("status", "Статус", 0x32, 0x30, timeout=1.0)
FULL_VERSION = Command("full_version", "Полная версия", 0x30, 0x31, timeout=1.0)


MT163 = Profile(
    key="mt163",
    title="MT163 — картоприёмник",
    baudrate=38400,
    model="MT163",
    version=VERSION,
    status=STATUS,
    full_version=FULL_VERSION,
    commands=(
        Command("eject", "Вернуть карту", 0x31, 0x30),
        Command("retain", "Забрать в бокс", 0x31, 0x33),
        Command("insert_front", "Приём спереди", 0x31, 0x31, timeout=15.0),
        Command("insert_back", "Приём сзади", 0x31, 0x32, timeout=15.0),
        Command(
            "timeout_recovery", "Возврат по таймауту", 0x32, 0x31,
            params=(Param("enabled", "Режим", (("включить", 1), ("выключить", 0)), default=1),),
            timeout=1.0,
        ),
    ),
    sensors=(
        Sensor(6, "Датчик Q3"),
        Sensor(5, "Датчик Q2"),
        Sensor(4, "Датчик Q1"),
        Sensor(3, "Приём карты"),
        Sensor(2, "Возврат карты"),
        Sensor(1, "Ошибка", alarm=True),
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
        Sensor(7, "Накопитель пуст", alarm=True),
        Sensor(6, "Карта у выхода"),
        Sensor(5, "Карта в тракте"),
        Sensor(4, "Мало карт", alarm=True),
        Sensor(3, "Выдача"),
        Sensor(2, "Сбор"),
        Sensor(1, "Ошибка выдачи", alarm=True),
        Sensor(0, "Автосбор"),
    ),
)

PROFILES = {profile.key: profile for profile in (MT163, MT166)}


def detect(version: str) -> Profile | None:
    text = version.upper()
    return next((p for p in PROFILES.values() if p.model in text), None)
