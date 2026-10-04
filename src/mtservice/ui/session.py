"""Подключение к устройству и мост из потока обмена в сигналы Qt."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from ..devices import MT163, PROFILES, Profile, detect
from ..emulator import Emulator
from ..link import Exchange, Link
from ..protocol import OK
from ..transport import SerialTransport

EMULATOR = "emulator:"


class Session(QObject):
    exchanged = Signal(object)
    status_changed = Signal(object)  # int или None, если устройство не ответило
    connection_changed = Signal(bool)
    profile_changed = Signal(object)
    message = Signal(str)

    _arrived = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.profile: Profile = MT163
        self.link: Link | None = None
        self.port = ""
        self.auto_detect = True
        self.polling = True
        self.poll_interval_ms = 300
        self._arrived.connect(self._handle)

    @property
    def connected(self) -> bool:
        return self.link is not None

    def open(self, port: str, baudrate: int, profile_key: str | None) -> bool:
        self.close()
        self.auto_detect = profile_key is None
        if profile_key:
            self.set_profile(PROFILES[profile_key])
        try:
            if port.startswith(EMULATOR):
                profile = PROFILES[port[len(EMULATOR):]]
                transport = Emulator(profile, delay=0.15)
            else:
                transport = SerialTransport(port, baudrate)
        except (OSError, ValueError) as exc:
            self.message.emit(f"Не удалось открыть {port}: {exc}")
            return False
        self.port = port
        self.link = Link(transport, listener=self._arrived.emit)
        self.link.start()
        self.connection_changed.emit(True)
        name = transport.name if isinstance(transport, Emulator) else port
        self.message.emit(f"{name}: порт открыт, запрашиваю версию…")
        self.link.submit(self.profile.version.frame(), 1.0, "connect")
        return True

    def close(self) -> None:
        if self.link is None:
            return
        link, self.link = self.link, None
        link.close()
        self.connection_changed.emit(False)
        self.status_changed.emit(None)

    def set_profile(self, profile: Profile) -> None:
        if profile is self.profile:
            return
        self.profile = profile
        self.profile_changed.emit(profile)
        self._apply_polling()

    def set_polling(self, enabled: bool, interval_ms: int) -> None:
        self.polling = enabled
        self.poll_interval_ms = interval_ms
        self._apply_polling()

    def send(self, frame: bytes, timeout: float = 2.0) -> None:
        if self.link:
            self.link.submit(frame, timeout, "user")

    def call(self, frame: bytes, timeout: float) -> Exchange:
        """Блокирующий вызов для потока сценария."""
        if self.link is None:
            raise RuntimeError("нет подключения")
        return self.link.call(frame, timeout, "script")

    def _apply_polling(self) -> None:
        if self.link is None:
            return
        frame = self.profile.status.frame() if self.polling else None
        self.link.set_polling(frame, self.poll_interval_ms / 1000, self.profile.status.timeout)

    @Slot(object)
    def _handle(self, exchange: Exchange) -> None:
        if self.link is None:
            return
        self.exchanged.emit(exchange)
        if exchange.port_error:
            self.message.emit(f"Связь с {self.port} потеряна: {exchange.error}")
            self.close()
            return
        if exchange.source == "connect":
            self._on_version(exchange)
        elif exchange.source == "poll":
            self.status_changed.emit(exchange.reply.status if exchange.ok else None)

    def _on_version(self, exchange: Exchange) -> None:
        reply = exchange.reply
        if reply is None or reply.status != OK:
            self.message.emit("Устройство не ответило на запрос версии — проверьте порт и скорость")
        else:
            version = reply.data.decode("ascii", "replace").strip()
            found = detect(version)
            if self.auto_detect and found:
                self.set_profile(found)
            note = "" if found else " (модель не распознана, выберите вручную)"
            self.message.emit(f"Подключено: {version}{note}")
        self._apply_polling()
