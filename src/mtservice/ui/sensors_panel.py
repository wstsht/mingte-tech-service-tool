from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..devices import Profile
from .session import Session

ACTIVE = {False: (QColor("#e2f3e5"), QColor("#1f6b33")), True: (QColor("#fbe1de"), QColor("#a8261b"))}
HISTORY_LIMIT = 1000


def _mono() -> QFont:
    font = QFont()
    font.setFamilies(["Consolas", "Courier New", "monospace"])
    return font


class SensorsPanel(QGroupBox):
    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__("Датчики", parent)
        self.session = session
        self._last: int | None = None

        self._poll = QCheckBox("Опрос")
        self._poll.setChecked(session.polling)
        self._interval = QSpinBox()
        self._interval.setRange(50, 5000)
        self._interval.setSingleStep(50)
        self._interval.setSuffix(" мс")
        self._interval.setValue(session.poll_interval_ms)
        self._poll.toggled.connect(self._apply_polling)
        self._interval.valueChanged.connect(self._apply_polling)
        self._raw = QLabel()
        self._raw.setFont(_mono())

        controls = QHBoxLayout()
        controls.addWidget(self._poll)
        controls.addWidget(self._interval)
        controls.addStretch(1)
        controls.addWidget(self._raw)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Сигнал", "Состояние"])
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setShowGrid(False)
        self._table.setFont(_mono())

        self._history = QListWidget()
        self._history.setFont(_mono())
        clear = QPushButton("Очистить историю")
        clear.clicked.connect(self._history.clear)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self._table)
        layout.addWidget(QLabel("Изменения:"))
        layout.addWidget(self._history, 1)
        layout.addWidget(clear)

        session.profile_changed.connect(self._build)
        session.status_changed.connect(self._show)
        self._build(session.profile)

    def _apply_polling(self) -> None:
        self.session.set_polling(self._poll.isChecked(), self._interval.value())

    def _build(self, profile: Profile) -> None:
        self._table.setRowCount(len(profile.sensors))
        for row, sensor in enumerate(profile.sensors):
            title = QTableWidgetItem(sensor.title)
            title.setToolTip(f"Бит {sensor.bit} байта статуса")
            state = QTableWidgetItem()
            state.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 0, title)
            self._table.setItem(row, 1, state)
        self._table.resizeRowsToContents()
        height = self._table.horizontalHeader().height() + 2 * self._table.frameWidth()
        height += sum(self._table.rowHeight(row) for row in range(self._table.rowCount()))
        self._table.setFixedHeight(height)
        self._last = None
        self._show(None)

    def _show(self, value: int | None) -> None:
        profile = self.session.profile
        if value is None:
            self._raw.setText("S = —")
            for row in range(self._table.rowCount()):
                self._paint(row, "—", None)
            self._last = None
            return
        self._raw.setText(f"S = 0x{value:02X}  {value:08b}")
        for row, state in enumerate(profile.sensor_states(value)):
            colors = ACTIVE[state.sensor.alarm] if state.on else None
            self._paint(row, state.text, colors)
        if self._last is not None and value != self._last:
            self._record(profile, self._last, value)
        self._last = value

    def _paint(self, row: int, text: str, colors: tuple[QColor, QColor] | None) -> None:
        background = QBrush(colors[0]) if colors else QBrush()
        state = self._table.item(row, 1)
        state.setText(text)
        state.setForeground(QBrush(colors[1]) if colors else QBrush())
        for column in range(2):
            self._table.item(row, column).setBackground(background)

    def _record(self, profile: Profile, before: int, after: int) -> None:
        moment = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        for sensor in profile.sensors:
            old, new = before >> sensor.bit & 1, after >> sensor.bit & 1
            if old != new:
                was = sensor.on if old else sensor.off
                now = sensor.on if new else sensor.off
                self._history.insertItem(0, f"{moment}  {sensor.title}: {was} → {now}")
        while self._history.count() > HISTORY_LIMIT:
            self._history.takeItem(self._history.count() - 1)
