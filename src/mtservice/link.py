from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .protocol import FrameReader, Reply, decode
from .transport import Transport

log = logging.getLogger(__name__)

FRAME_GAP = 0.02
NAK = 0x15

_STOP = object()
_WAKE = object()


class LinkClosed(RuntimeError):
    pass


@dataclass(frozen=True)
class Exchange:
    request: bytes
    response: bytes | None
    source: str
    started: datetime
    elapsed: float
    error: str | None = None
    skipped: int = 0
    port_error: bool = False
    nak: bool = False
    reply: Reply | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if self.response is not None:
            object.__setattr__(self, "reply", decode(self.response))

    @property
    def ok(self) -> bool:
        return self.reply is not None


class Link:
    def __init__(
        self,
        transport: Transport,
        *,
        gap: float = FRAME_GAP,
        listener: Callable[[Exchange], None] | None = None,
    ) -> None:
        self._transport = transport
        self._gap = gap
        self._listener = listener
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._last_end = 0.0
        self._poll_frame: bytes | None = None
        self._poll_interval = 0.3
        self._poll_timeout = 1.0
        self._next_poll = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="link", daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._jobs.put(_STOP)
        if self._thread:
            self._thread.join(timeout=10)
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            if isinstance(job, tuple):
                job[3].set_exception(LinkClosed("соединение закрыто"))
        self._transport.close()

    def submit(self, frame: bytes, timeout: float = 2.0, source: str = "user") -> Future:
        if self._closed:
            raise LinkClosed("соединение закрыто")
        future: Future = Future()
        self._jobs.put((frame, timeout, source, future))
        return future

    def call(self, frame: bytes, timeout: float = 2.0, source: str = "user") -> Exchange:
        return self.submit(frame, timeout, source).result()

    def set_polling(self, frame: bytes | None, interval: float = 0.3, timeout: float = 1.0) -> None:
        self._poll_frame = frame
        self._poll_interval = interval
        self._poll_timeout = timeout
        self._next_poll = time.monotonic()
        self._jobs.put(_WAKE)

    def _run(self) -> None:
        while True:
            wait = None
            if self._poll_frame is not None:
                wait = max(0.0, self._next_poll - time.monotonic())
            try:
                job = self._jobs.get(timeout=wait)
            except queue.Empty:
                job = None
            if job is _STOP:
                return
            if job is _WAKE:
                continue
            if job is None:
                frame = self._poll_frame
                if frame is not None:
                    self._execute(frame, self._poll_timeout, "poll")
                    self._next_poll = time.monotonic() + self._poll_interval
                continue
            frame, timeout, source, future = job
            if self._closed:
                future.set_exception(LinkClosed("соединение закрыто"))
            elif future.set_running_or_notify_cancel():
                future.set_result(self._execute(frame, timeout, source))

    def _execute(self, frame: bytes, timeout: float, source: str) -> Exchange:
        expected = decode(frame)
        pause = self._gap - (time.monotonic() - self._last_end)
        if pause > 0:
            time.sleep(pause)

        started = datetime.now()
        begin = time.monotonic()
        reader = FrameReader()
        response = None
        error = None
        port_error = False
        nak = False
        received = bytearray()
        try:
            self._transport.discard_input()
            self._transport.write(frame)
            deadline = begin + timeout
            while response is None:
                left = deadline - time.monotonic()
                if left <= 0:
                    error = "ответ не распознан" if reader.skipped or reader.pending else "нет ответа"
                    break
                chunk = self._transport.read(min(left, 0.05))
                received += chunk
                if received and received.count(NAK) == len(received):
                    nak = True
                    error = "устройство не поддерживает команду (NAK)"
                    break
                for candidate in reader.feed(chunk):
                    reply = decode(candidate)
                    if (reply.cm, reply.pm) == (expected.cm, expected.pm):
                        response = candidate
                        break
                    reader.skipped += len(candidate)
        except OSError as exc:
            error = f"ошибка порта: {exc}"
            port_error = True
        self._last_end = time.monotonic()

        exchange = Exchange(
            request=frame,
            response=response,
            source=source,
            started=started,
            elapsed=self._last_end - begin,
            error=error,
            skipped=reader.skipped,
            port_error=port_error,
            nak=nak,
        )
        if self._listener:
            try:
                self._listener(exchange)
            except Exception:
                log.exception("ошибка в обработчике обмена")
        return exchange
