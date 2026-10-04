from __future__ import annotations

from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..devices import Command, Profile
from ..format import hex_bytes, raw_frame
from .params import ParamEditor
from .session import Session


def _tooltip(command: Command) -> str:
    lines = [f"CM PM: {command.cm:02X} {command.pm:02X}"]
    if not command.documented:
        lines.append("Команды нет в документации производителя.")
    if command.note:
        lines.append(command.note)
    return "\n".join(lines)


class CommandsPanel(QWidget):
    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._mechanics = QGroupBox("Механика")
        self._service = QGroupBox("Служебные")
        self._raw = QGroupBox("Произвольный кадр")

        self._raw_input = QLineEdit()
        self._raw_input.setPlaceholderText("31 30  или кадр целиком: 02 00 02 31 30 03 02")
        self._raw_input.returnPressed.connect(self._send_raw)
        self._raw_button = QPushButton("Отправить")
        self._raw_button.clicked.connect(self._send_raw)
        raw_layout = QHBoxLayout(self._raw)
        raw_layout.addWidget(self._raw_input, 1)
        raw_layout.addWidget(self._raw_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._mechanics)
        layout.addWidget(self._service)
        layout.addWidget(self._raw)
        layout.addStretch(1)

        session.profile_changed.connect(self._build)
        session.connection_changed.connect(self._set_enabled)
        self._build(session.profile)
        self._set_enabled(session.connected)

    def _build(self, profile: Profile) -> None:
        for box, commands in ((self._mechanics, profile.commands),
                              (self._service, (profile.version, profile.status))):
            if box.layout() is None:
                QVBoxLayout(box).setContentsMargins(0, 0, 0, 0)
            old = box.findChild(QWidget, "content")
            if old is not None:
                old.setParent(None)
                old.deleteLater()
            content = QWidget(objectName="content")
            box.layout().addWidget(content)
            grid = QGridLayout(content)
            for row, command in enumerate(commands):
                title = command.title if command.documented else f"{command.title} *"
                button = QPushButton(title)
                button.setToolTip(_tooltip(command))
                editor = ParamEditor(command)
                button.clicked.connect(lambda _=False, c=command, e=editor: self._send(c, e))
                grid.addWidget(button, row, 0)
                grid.addWidget(editor, row, 1)
            grid.setColumnStretch(0, 1)
        self._set_enabled(self.session.connected)

    def _set_enabled(self, connected: bool) -> None:
        for box in (self._mechanics, self._service, self._raw):
            box.setEnabled(connected)

    def _send(self, command: Command, editor: ParamEditor) -> None:
        try:
            frame = command.frame(editor.values())
        except ValueError as exc:
            self.session.message.emit(str(exc))
            return
        self.session.send(frame, command.timeout)

    def _send_raw(self) -> None:
        try:
            frame = raw_frame(self._raw_input.text())
        except ValueError as exc:
            self.session.message.emit(f"Произвольный кадр: {exc}")
            return
        self.session.message.emit(f"Отправляю {hex_bytes(frame)}")
        self.session.send(frame)
