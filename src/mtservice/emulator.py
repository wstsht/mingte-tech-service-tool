from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from . import bootloader
from .devices import MT163, MT166, Profile
from .protocol import OK, FrameReader, Reply, decode, encode

REFUSED = 0x4E
NAK = 0x15


@dataclass
class MT163State:
    card: str | None = None
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
        elif key == "timeout_recovery":
            self.timeout_recovery = bool(data[:1] == b"\x01")
        else:
            return REFUSED
        return OK


@dataclass
class MT166State:
    hopper: int = 30
    collected: int = 0
    card: str | None = None

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


class _Port:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self._output = bytearray()
        self._ready_at = 0.0
        self._changed = threading.Condition()

    def _emit(self, data: bytes) -> None:
        with self._changed:
            self._output += data
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


class BootloaderEmulator(_Port):
    name = "Эмулятор загрузчика"

    def __init__(self, delay: float = 0.0, reset_after: float | None = None) -> None:
        super().__init__(delay)
        self.stage = "app"
        self.image = bytearray()
        self.finished = False
        self.broken_block: int | None = None
        if reset_after is not None:
            timer = threading.Timer(reset_after, self.press_reset)
            timer.daemon = True
            timer.start()

    def press_reset(self) -> None:
        self.stage = "hello"
        self.image.clear()
        self.finished = False
        self._emit(bootloader.HELLO)

    def write(self, data: bytes) -> None:
        if self.stage == "hello" and data == bootloader.MAGIC:
            self.stage = "ident"
            self._emit(bootloader.IDENT)
        elif self.stage == "ident" and data == bootloader.IDENT:
            self.stage = "blocks"
            self._emit(bootloader.READY)
        elif self.stage == "blocks" and data == bootloader.END:
            self.stage = "app"
            self.finished = True
        elif self.stage == "blocks" and len(data) == bootloader.BLOCK + 3:
            number = int.from_bytes(data[:2], "big")
            payload = data[2:-1]
            expected = len(self.image) // bootloader.BLOCK
            if number == expected and sum(payload) & 0xFF == data[-1] and number != self.broken_block:
                self.image += payload
                self._emit(bootloader.ACK)


class Emulator(_Port):
    VERSIONS = {"MT163": "MT163 V3.10C", "MT166": "MT166 V3.003"}

    def __init__(self, profile: Profile, delay: float = 0.0) -> None:
        super().__init__(delay)
        self.profile = profile
        self.version = self.VERSIONS[profile.model]
        self.state = MT163State() if profile is MT163 else MT166State()
        self._reader = FrameReader()

    @property
    def name(self) -> str:
        return f"Эмулятор {self.profile.model}"

    def write(self, data: bytes) -> None:
        for frame in self._reader.feed(data):
            self._emit(self._answer(decode(frame)))

    def _answer(self, request: Reply) -> bytes:
        command = self.profile.find(request.cm, request.pm)
        if command is None:
            return bytes((NAK,))
        if command.key == "version":
            body = bytes((OK,)) + self.version[:12].encode("ascii")
        elif command.key == "full_version":
            body = bytes((OK,)) + self.version.encode("ascii").ljust(13, b"\0")
        elif command.key == "status":
            body = bytes((self.state.status(),))
        else:
            body = bytes((self.state.handle(command.key, request.body),))
        return encode(request.cm, request.pm, body)
