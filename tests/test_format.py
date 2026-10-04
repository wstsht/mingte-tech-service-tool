from datetime import datetime

import pytest

from mtservice.devices import MT163, MT166
from mtservice.format import failed, hex_bytes, log_line, raw_frame, summary
from mtservice.link import Exchange
from mtservice.protocol import encode


def exchange(request: bytes, response: bytes | None, error: str | None = None, source="user"):
    return Exchange(
        request=request,
        response=response,
        source=source,
        started=datetime(2026, 10, 4, 12, 3, 1, 250000),
        elapsed=0.84,
        error=error,
    )


def test_hex_bytes():
    assert hex_bytes(bytes.fromhex("020002")) == "02 00 02"


def test_summary_for_mechanics():
    request = MT163.command("eject").frame()
    assert summary(exchange(request, encode(0x31, 0x30, b"\x59")), MT163) == "Вернуть карту: успешно"
    assert summary(exchange(request, encode(0x31, 0x30, b"\x4e")), MT163) == "Вернуть карту: отказ"
    assert summary(exchange(request, None, "нет ответа"), MT163) == "Вернуть карту: нет ответа"


def test_summary_for_status_lists_active_sensors():
    request = MT163.status.frame()
    assert summary(exchange(request, encode(0x32, 0x30, b"\x30")), MT163) == (
        "Статус: 0x30 — Датчик Q2, Датчик Q1"
    )
    assert summary(exchange(request, encode(0x32, 0x30, b"\x00")), MT163) == "Статус: 0x00 — всё сброшено"


def test_summary_for_version():
    request = MT166.version.frame()
    reply = encode(0x30, 0x30, b"\x59MT166 V1.143")
    assert summary(exchange(request, reply), MT166) == "Версия: MT166 V1.143"


def test_summary_for_unknown_command():
    request = encode(0x40, 0x41)
    assert summary(exchange(request, encode(0x40, 0x41, b"\x59\x01")), MT163) == "40 41: успешно, данные 01"


def test_log_line():
    request = MT163.command("eject").frame()
    line = log_line(exchange(request, encode(0x31, 0x30, b"\x59")), MT163)
    assert line == (
        "12:03:01.250  кнопка    >> 02 00 02 31 30 03 02  << 02 00 03 31 30 59 03 5A"
        "  Вернуть карту: успешно  0.84 с"
    )


def test_log_line_without_answer():
    request = MT163.status.frame()
    line = log_line(exchange(request, None, "нет ответа", source="poll"), MT163)
    assert "опрос" in line and "<< —" in line


@pytest.mark.parametrize(
    "text, frame",
    [
        ("31 30", "02 00 02 31 30 03 02"),
        ("3130", "02 00 02 31 30 03 02"),
        ("32 33 81", "02 00 03 32 33 81 03 82"),
        ("02 00 02 31 30 03 02", "02 00 02 31 30 03 02"),
        ("0x31 0x33", "02 00 02 31 33 03 01"),
    ],
)
def test_raw_frame(text, frame):
    assert raw_frame(text) == bytes.fromhex(frame)


@pytest.mark.parametrize("text", ["", "31", "zz 30", "3 1 30"])
def test_raw_frame_rejects(text):
    with pytest.raises(ValueError):
        raw_frame(text)


def test_failed():
    status = MT163.status.frame()
    eject = MT163.command("eject").frame()
    assert not failed(exchange(status, encode(0x32, 0x30, b"\x70")), MT163)
    assert failed(exchange(status, None, "нет ответа"), MT163)
    assert not failed(exchange(eject, encode(0x31, 0x30, b"\x59")), MT163)
    assert failed(exchange(eject, encode(0x31, 0x30, b"\x4e")), MT163)
