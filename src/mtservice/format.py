from __future__ import annotations

import re

from .devices import Profile
from .link import Exchange
from .protocol import OK, FrameError, decode, encode, status_text

SOURCES = {"user": "кнопка", "script": "сценарий", "poll": "опрос", "connect": "подключение"}


def hex_bytes(data: bytes) -> str:
    return data.hex(" ").upper()


def summary(exchange: Exchange, profile: Profile) -> str:
    request = decode(exchange.request)
    command = profile.find(request.cm, request.pm)
    title = command.title if command else f"{request.cm:02X} {request.pm:02X}"
    reply = exchange.reply
    if reply is None:
        return f"{title}: {exchange.error or 'нет ответа'}"
    if reply.status is None:
        return f"{title}: пустой ответ"
    key = command.key if command else ""
    if key == "status":
        active = ", ".join(profile.active_sensors(reply.status)) or "всё сброшено"
        return f"{title}: 0x{reply.status:02X} — {active}"
    if key == "version" and reply.status == OK:
        return f"{title}: {reply.data.decode('ascii', 'replace').strip()}"
    text = f"{title}: {status_text(reply.status)}"
    if reply.data:
        text += f", данные {hex_bytes(reply.data)}"
    return text


def failed(exchange: Exchange, profile: Profile) -> bool:
    if exchange.reply is None:
        return True
    request = decode(exchange.request)
    if request.cm == profile.status.cm and request.pm == profile.status.pm:
        return False
    return exchange.reply.status != OK


def log_line(exchange: Exchange, profile: Profile) -> str:
    moment = exchange.started.strftime("%H:%M:%S.") + f"{exchange.started.microsecond // 1000:03d}"
    source = SOURCES.get(exchange.source, exchange.source)
    answer = hex_bytes(exchange.response) if exchange.response else "—"
    return (
        f"{moment}  {source:<8}  >> {hex_bytes(exchange.request)}  << {answer}"
        f"  {summary(exchange, profile)}  {exchange.elapsed:.2f} с"
    )


def raw_frame(text: str) -> bytes:
    """Принимает «CM PM [данные]» или готовый кадр целиком, в hex."""
    tokens = text.replace(",", " ").split()
    tokens = [t[2:] if t.lower().startswith("0x") else t for t in tokens]
    if any(len(t) % 2 for t in tokens) or not all(re.fullmatch(r"[0-9A-Fa-f]*", t) for t in tokens):
        raise ValueError("нужны байты в hex, например: 31 30")
    data = bytes.fromhex("".join(tokens))
    try:
        decode(data)
        return data
    except FrameError:
        pass
    if len(data) < 2:
        raise ValueError("нужно минимум два байта: команда и параметр")
    return encode(data[0], data[1], data[2:])
