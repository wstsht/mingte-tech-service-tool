"""Кадр Mingte: STX LenH LenL CM PM [данные] ETX BCC.

Len считает байты от CM до конца данных, BCC — XOR всех байтов от STX до ETX.
В ответе сразу за CM PM идёт байт статуса (P или S), потом данные.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import reduce

STX = 0x02
ETX = 0x03
MAX_LENGTH = 1024

OK = 0x59  # 'Y'

STATUS_TEXT = {
    0x59: "успешно",
    0x4E: "отказ",
    0x45: "нет карты",
    0x57: "карта не в рабочей позиции",
}


class FrameError(ValueError):
    pass


def bcc(data: bytes) -> int:
    return reduce(lambda acc, byte: acc ^ byte, data, 0)


def encode(cm: int, pm: int, data: bytes = b"") -> bytes:
    body = bytes((cm, pm)) + bytes(data)
    frame = bytes((STX,)) + len(body).to_bytes(2, "big") + body + bytes((ETX,))
    return frame + bytes((bcc(frame),))


@dataclass(frozen=True)
class Reply:
    cm: int
    pm: int
    body: bytes

    @property
    def status(self) -> int | None:
        return self.body[0] if self.body else None

    @property
    def data(self) -> bytes:
        return self.body[1:]


def decode(frame: bytes) -> Reply:
    if len(frame) < 7:
        raise FrameError("кадр короче 7 байт")
    if frame[0] != STX:
        raise FrameError("кадр не начинается с STX")
    length = int.from_bytes(frame[1:3], "big")
    if len(frame) != length + 5:
        raise FrameError("длина кадра не совпадает с заявленной")
    if frame[-2] != ETX:
        raise FrameError("нет ETX перед BCC")
    if bcc(frame[:-1]) != frame[-1]:
        raise FrameError("не сошлась BCC")
    return Reply(frame[3], frame[4], bytes(frame[5:-2]))


def status_text(code: int) -> str:
    return STATUS_TEXT.get(code, f"код 0x{code:02X}")


class FrameReader:
    """Собирает кадры из потока байтов, пропуская мусор на линии."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.skipped = 0

    @property
    def pending(self) -> int:
        return len(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()
        self.skipped = 0

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buffer += chunk
        frames = []
        while True:
            start = self._buffer.find(STX)
            if start < 0:
                self._skip(len(self._buffer))
                break
            self._skip(start)
            if len(self._buffer) < 3:
                break
            length = int.from_bytes(self._buffer[1:3], "big")
            if not 2 <= length <= MAX_LENGTH:
                self._skip(1)
                continue
            if len(self._buffer) < length + 5:
                break
            candidate = bytes(self._buffer[: length + 5])
            try:
                decode(candidate)
            except FrameError:
                self._skip(1)
                continue
            frames.append(candidate)
            del self._buffer[: length + 5]
        return frames

    def _skip(self, count: int) -> None:
        self.skipped += count
        del self._buffer[:count]
