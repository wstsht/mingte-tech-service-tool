"""Упрощённая модель устройства для работы без железа и для тестов.

Отвечает теми же кадрами, что и настоящее устройство, но механику
изображает условно: только положения карты, без времени движения.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .devices import MT163, MT166, Profile
from .protocol import OK, FrameReader, Reply, decode, encode

REFUSED = 0x4E


@dataclass
class MT163State:
    card: str | None = None  # None, "entry", "read"
    retained: int = 0
    timeout_recovery: bool = True

    def status(self) -> int:
        return {None: 0x00, "entry": 0x10, "read": 0x71}[self.card]

    def handle(self, key: str, data: bytes) -> int:
        if key in ("insert_front", "insert_back"):
            self.card = "read"
        elif key == "eject":
            if self.card is None:
                return REFUSED
            self.card = "entry"
        elif key == "retain":
            if self.card is None:
                return REFUSED
            self.card = None
            self.retained += 1
        elif key == "move":
            if self.card is None:
                return REFUSED
        elif key == "timeout_recovery":
            self.timeout_recovery = bool(data[:1] == b"\x01")
        else:
            return REFUSED
        return OK


@dataclass
class MT166State:
    hopper: int = 30
    collected: int = 0
    card: str | None = None  # None, "read", "bezel"

    def status(self) -> int:
        value = 0x01
        if self.hopper == 0:
            value |= 0x80
        elif self.hopper <= 5:
            value |= 0x10
        if self.card == "bezel":
            value |= 0x40
        if self.card == "read":
            value |= 0x20
        return value

    def _take(self) -> bool:
        if self.hopper == 0:
            return False
        self.hopper -= 1
        return True

    def handle(self, key: str, data: bytes) -> int:
        if key in ("to_read", "to_bezel", "to_outside"):
            if self.card is None and not self._take():
                return REFUSED
            if key == "to_read" and self.card == "bezel":
                return REFUSED
            self.card = {"to_read": "read", "to_bezel": "bezel", "to_outside": None}[key]
        elif key == "collect":
            if self.card is None:
                return REFUSED
            self.card = None
            self.collected += 1
        else:
            return REFUSED
        return OK


class Emulator:
    def __init__(self, profile: Profile, delay: float = 0.0) -> None:
        self.profile = profile
        self.delay = delay
        self.state = MT163State() if profile is MT163 else MT166State()
        self._reader = FrameReader()
        self._output = bytearray()
        self._ready_at = 0.0
        self._changed = threading.Condition()

    @property
    def name(self) -> str:
        return f"Эмулятор {self.profile.model}"

    def write(self, data: bytes) -> None:
        replies = [self._answer(decode(frame)) for frame in self._reader.feed(data)]
        with self._changed:
            for reply in replies:
                self._output += reply
            if replies:
                self._ready_at = time.monotonic() + self.delay
                self._changed.notify_all()

    def read(self, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        with self._changed:
            while True:
                now = time.monotonic()
                if self._output and now >= self._ready_at:
                    data = bytes(self._output)
                    self._output.clear()
                    return data
                if now >= deadline:
                    return b""
                wake = deadline if not self._output else min(deadline, self._ready_at)
                self._changed.wait(wake - now)

    def discard_input(self) -> None:
        with self._changed:
            self._output.clear()

    def close(self) -> None:
        self.discard_input()

    def _answer(self, request: Reply) -> bytes:
        command = self.profile.find(request.cm, request.pm)
        key = command.key if command else ""
        if key == "version":
            body = bytes((OK,)) + f"{self.profile.model} EMULATOR".encode("ascii")
        elif key == "status":
            body = bytes((self.state.status(),))
        else:
            body = bytes((self.state.handle(key, request.body),))
        return encode(request.cm, request.pm, body)
