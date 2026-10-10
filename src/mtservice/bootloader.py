from __future__ import annotations

import re
import struct
import threading
import time
from typing import Callable

from .transport import Transport

BAUDRATE = 115200
APP_BASE = 0x08002000
APP_LIMIT = 0xE000
BLOCK = 256

HELLO = b"318"
MAGIC = bytes.fromhex("37 46 52 83 44 85 62")
IDENT = b"MT318%"
READY = b"OK"
ACK = b"!"
END = b"\xff\xff"


class FlashError(RuntimeError):
    pass


class FlashCancelled(FlashError):
    pass


def blocks(image: bytes) -> list[bytes]:
    result = []
    for number, offset in enumerate(range(0, len(image), BLOCK)):
        data = image[offset:offset + BLOCK].ljust(BLOCK, b"\xff")
        result.append(number.to_bytes(2, "big") + data + bytes((sum(data) & 0xFF,)))
    return result


def image_version(image: bytes) -> str | None:
    match = re.search(rb"MT16\d V\d\.[0-9A-Z]{3,4}", image)
    return match.group().decode("ascii") if match else None


def check_image(image: bytes) -> None:
    if not 8 <= len(image) <= APP_LIMIT:
        raise FlashError(f"неподходящий размер образа: {len(image)} байт")
    stack, reset = struct.unpack_from("<II", image)
    if not 0x20000000 < stack <= 0x20010000 or not APP_BASE <= (reset & ~1) < APP_BASE + len(image):
        raise FlashError(f"образ не рассчитан на запуск с адреса {APP_BASE:#010x}")


class Flasher:
    def __init__(
        self,
        transport: Transport,
        image: bytes,
        *,
        on_stage: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        hello_timeout: float = 60.0,
        reply_timeout: float = 1.0,
        block_timeout: float = 2.0,
    ) -> None:
        check_image(image)
        self._transport = transport
        self._blocks = blocks(image)
        self._on_stage = on_stage or (lambda text: None)
        self._on_progress = on_progress or (lambda done, total: None)
        self._hello_timeout = hello_timeout
        self._reply_timeout = reply_timeout
        self._block_timeout = block_timeout
        self._cancel = threading.Event()

    @property
    def total(self) -> int:
        return len(self._blocks)

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        self._transport.discard_input()
        self._on_stage("Нажмите кнопку сброса на плате устройства")
        self._wait(HELLO, self._hello_timeout, "устройство не вошло в загрузчик")

        self._on_stage("Связь с загрузчиком")
        self._send(MAGIC)
        self._wait(IDENT, self._reply_timeout, "загрузчик не ответил на приветствие")
        self._send(IDENT)
        self._wait(READY, self._reply_timeout, "загрузчик не готов принимать прошивку")

        self._on_stage("Запись прошивки")
        for number, block in enumerate(self._blocks, 1):
            self._send(block, discard=False)
            self._wait(ACK, self._block_timeout, f"загрузчик не подтвердил блок {number} из {self.total}")
            self._on_progress(number, self.total)
        self._send(END, discard=False)
        time.sleep(0.3)
        self._on_stage("Прошивка записана")

    def _send(self, data: bytes, discard: bool = True) -> None:
        if self._cancel.is_set():
            raise FlashCancelled("прошивка отменена")
        time.sleep(0.01)
        if discard:
            self._transport.discard_input()
        self._transport.write(data)

    def _wait(self, token: bytes, timeout: float, message: str) -> None:
        buffer = bytearray()
        deadline = time.monotonic() + timeout
        while token not in buffer:
            if self._cancel.is_set():
                raise FlashCancelled("прошивка отменена")
            left = deadline - time.monotonic()
            if left <= 0:
                raise FlashError(message)
            buffer += self._transport.read(min(left, 0.05))
            if token == ACK and HELLO in buffer:
                raise FlashError("устройство перезагрузилось во время прошивки")
