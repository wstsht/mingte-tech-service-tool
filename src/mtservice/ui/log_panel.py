from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..format import failed, log_line
from ..link import Exchange
from .colors import ERROR, NOTE, is_dark
from .session import Session

LINE_LIMIT = 20000


class LogPanel(QGroupBox):
    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__("Журнал обмена", parent)
        self.session = session

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(LINE_LIMIT)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setFamilies(["Consolas", "Courier New", font.family()])
        self._view.setFont(font)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._show_polls = QCheckBox("Показывать опрос")
        clear = QPushButton("Очистить")
        clear.clicked.connect(self._view.clear)
        save = QPushButton("Сохранить…")
        save.clicked.connect(self._save)

        controls = QHBoxLayout()
        controls.addWidget(self._show_polls)
        controls.addStretch(1)
        controls.addWidget(clear)
        controls.addWidget(save)

        layout = QVBoxLayout(self)
        layout.addWidget(self._view, 1)
        layout.addLayout(controls)

        session.exchanged.connect(self._on_exchange)
        session.message.connect(self.note)

    def note(self, text: str) -> None:
        moment = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._append(f"{moment}  {text}", NOTE[is_dark(self._view.palette())])

    def _on_exchange(self, exchange: Exchange) -> None:
        if exchange.source == "poll" and not self._show_polls.isChecked():
            return
        profile = self.session.profile
        color = ERROR[is_dark(self._view.palette())] if failed(exchange, profile) else None
        self._append(log_line(exchange, profile), color)

    def _append(self, text: str, color: str | None) -> None:
        escaped = html.escape(text)
        style = "white-space: pre;" + (f" color: {color};" if color else "")
        self._view.appendHtml(f'<span style="{style}">{escaped}</span>')

    def _save(self) -> None:
        name = f"mtservice-{datetime.now():%Y%m%d-%H%M%S}.log"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить журнал", name, "Журнал (*.log *.txt)")
        if path:
            Path(path).write_text(self._view.toPlainText(), encoding="utf-8")
