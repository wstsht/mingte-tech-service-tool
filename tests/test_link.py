import threading
import time

import pytest
import serial

from mtservice.devices import MT163
from mtservice.emulator import Emulator
from mtservice.link import Link, LinkClosed
from mtservice.protocol import encode


class Silent:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append((time.monotonic(), data))

    def read(self, timeout):
        time.sleep(timeout)
        return b""

    def discard_input(self):
        pass

    def close(self):
        pass


class Scripted(Silent):
    """Отдаёт заранее заготовленные байты после каждой записи."""

    def __init__(self, answer: bytes):
        super().__init__()
        self.answer = answer
        self.pending = b""

    def write(self, data):
        super().write(data)
        self.pending = self.answer

    def read(self, timeout):
        data, self.pending = self.pending, b""
        if not data:
            time.sleep(timeout)
        return data


class Broken(Silent):
    def write(self, data):
        raise serial.SerialException("порт пропал")


@pytest.fixture
def opened():
    links = []

    def make(transport, **kwargs):
        link = Link(transport, **kwargs)
        link.start()
        links.append(link)
        return link

    yield make
    for link in links:
        link.close()


def test_call_returns_decoded_reply(opened):
    link = opened(Emulator(MT163))
    exchange = link.call(MT163.version.frame())
    assert exchange.ok
    assert exchange.source == "user"
    assert exchange.reply.data.startswith(b"MT163")
    assert exchange.request == MT163.version.frame()


def test_timeout_without_answer(opened):
    link = opened(Silent())
    started = time.monotonic()
    exchange = link.call(MT163.status.frame(), timeout=0.1)
    assert not exchange.ok
    assert exchange.error == "нет ответа"
    assert time.monotonic() - started < 1


def test_noise_before_reply_is_skipped(opened):
    reply = encode(0x32, 0x30, b"\x10")
    link = opened(Scripted(bytes.fromhex("78 7F F8") + reply))
    exchange = link.call(MT163.status.frame(), timeout=0.3)
    assert exchange.ok
    assert exchange.skipped == 3
    assert exchange.response == reply


def test_reply_to_other_command_is_not_accepted(opened):
    link = opened(Scripted(encode(0x31, 0x30, b"\x59")))
    exchange = link.call(MT163.status.frame(), timeout=0.15)
    assert not exchange.ok
    assert exchange.error == "ответ не распознан"


def test_nak_is_reported_without_waiting_for_timeout(opened):
    link = opened(Scripted(b"\x15"))
    started = time.monotonic()
    exchange = link.call(MT163.status.frame(), timeout=2.0)
    assert exchange.nak
    assert exchange.error == "устройство не поддерживает команду (NAK)"
    assert time.monotonic() - started < 0.5


def test_port_failure_is_reported(opened):
    link = opened(Broken())
    exchange = link.call(MT163.status.frame(), timeout=0.1)
    assert exchange.port_error
    assert exchange.error.startswith("ошибка порта")


def test_frames_are_separated_by_gap(opened):
    transport = Silent()
    link = opened(transport, gap=0.05)
    for _ in range(3):
        link.call(MT163.status.frame(), timeout=0.01)
    moments = [moment for moment, _ in transport.writes]
    assert all(b - a >= 0.05 for a, b in zip(moments, moments[1:]))


def test_polling_reports_status_until_stopped(opened):
    seen = []
    link = opened(Emulator(MT163), listener=seen.append)
    link.set_polling(MT163.status.frame(), interval=0.02)
    time.sleep(0.3)
    link.set_polling(None)
    polls = [e for e in seen if e.source == "poll"]
    assert len(polls) >= 3
    assert all(e.ok for e in polls)
    count = len(seen)
    time.sleep(0.15)
    assert len(seen) == count


def test_commands_run_between_polls(opened):
    device = Emulator(MT163)
    link = opened(device)
    link.set_polling(MT163.status.frame(), interval=0.01)
    assert link.call(MT163.command("insert_front").frame()).reply.status == 0x59
    assert device.state.card == "read"


def test_listener_errors_do_not_stop_the_worker(opened):
    def explode(exchange):
        raise RuntimeError("boom")

    link = opened(Emulator(MT163), listener=explode)
    assert link.call(MT163.status.frame()).ok
    assert link.call(MT163.status.frame()).ok


def test_submit_after_close_fails():
    link = Link(Emulator(MT163))
    link.start()
    link.close()
    with pytest.raises(LinkClosed):
        link.submit(MT163.status.frame())


def test_close_cancels_queued_requests():
    link = Link(Silent())
    link.start()
    futures = [link.submit(MT163.status.frame(), timeout=0.2) for _ in range(5)]
    link.close()
    done = [f for f in futures if not f.cancelled() and f.exception() is None]
    failed = [f for f in futures if f.cancelled() or isinstance(f.exception(), LinkClosed)]
    assert len(done) + len(failed) == 5
    assert failed


def test_calls_from_several_threads(opened):
    link = opened(Emulator(MT163))
    results = []

    def worker():
        for _ in range(5):
            results.append(link.call(MT163.status.frame()).ok)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [True] * 20
