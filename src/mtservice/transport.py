from __future__ import annotations

from typing import Protocol

import serial
from serial.tools import list_ports


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...

    def read(self, timeout: float) -> bytes:
        """Ждёт до timeout секунд и возвращает всё, что успело прийти."""
        ...

    def discard_input(self) -> None: ...

    def close(self) -> None: ...


class SerialTransport:
    def __init__(self, port: str, baudrate: int) -> None:
        self._serial = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0,
            write_timeout=1,
        )

    def write(self, data: bytes) -> None:
        self._serial.write(data)
        self._serial.flush()

    def read(self, timeout: float) -> bytes:
        self._serial.timeout = timeout
        first = self._serial.read(1)
        if not first:
            return b""
        self._serial.timeout = 0
        return first + self._serial.read(self._serial.in_waiting)

    def discard_input(self) -> None:
        self._serial.reset_input_buffer()

    def close(self) -> None:
        self._serial.close()


def available_ports() -> list[tuple[str, str]]:
    ports = sorted(list_ports.comports(), key=lambda p: (len(p.device), p.device))
    return [(p.device, p.description or "") for p in ports]
