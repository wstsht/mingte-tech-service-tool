from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..devices import Profile
from .session import Session

COLORS = {"on": "#2e9e4f", "alarm": "#d63b30", "off": "#c9ced6", "lost": "#f0f1f3"}
HISTORY_LIMIT = 1000


class Indicator(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(14, 14)
        self.set_color("lost")

    def set_color(self, name: str) -> None:
        self.setStyleSheet(
            f"background: {COLORS[name]}; border: 1px solid #8a919c; border-radius: 7px;"
        )


class SensorsPanel(QGroupBox):
    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__("Датчики", parent)
        self.session = session
        self._last: int | None = None
        self._rows: list[tuple[int, Indicator, QLabel]] = []

        self._poll = QCheckBox("Опрос")
        self._poll.setChecked(session.polling)
        self._interval = QSpinBox()
        self._interval.setRange(50, 5000)
        self._interval.setSingleStep(50)
        self._interval.setSuffix(" мс")
        self._interval.setValue(session.poll_interval_ms)
        self._poll.toggled.connect(self._apply_polling)
        self._interval.valueChanged.connect(self._apply_polling)

        controls = QHBoxLayout()
        controls.addWidget(self._poll)
        controls.addWidget(self._interval)
        controls.addStretch(1)

        self._raw = QLabel("S = —")
        self._raw.setStyleSheet("font-family: Consolas, monospace; font-size: 13px;")
        self._grid_host = QWidget()

        self._history = QListWidget()
        self._history.setStyleSheet("font-family: Consolas, monospace;")
        clear = QPushButton("Очистить историю")
        clear.clicked.connect(self._history.clear)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self._raw)
        layout.addWidget(self._grid_host)
        layout.addWidget(QLabel("Изменения:"))
        layout.addWidget(self._history, 1)
        layout.addWidget(clear)

        session.profile_changed.connect(self._build)
        session.status_changed.connect(self._show)
        self._build(session.profile)

    def _apply_polling(self) -> None:
        self.session.set_polling(self._poll.isChecked(), self._interval.value())

    def _build(self, profile: Profile) -> None:
        old = self._grid_host.layout()
        if old is not None:
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QWidget().setLayout(old)
        grid = QGridLayout(self._grid_host)
        grid.setContentsMargins(0, 4, 0, 4)
        self._rows = []
        for row, sensor in enumerate(profile.sensors):
            indicator = Indicator()
            state = QLabel("—")
            grid.addWidget(indicator, row, 0)
            grid.addWidget(QLabel(f"b{sensor.bit}  {sensor.title}"), row, 1)
            grid.addWidget(state, row, 2)
            self._rows.append((sensor.bit, indicator, state))
        grid.setColumnStretch(1, 1)
        self._last = None
        self._show(None)

    def _show(self, value: int | None) -> None:
        profile = self.session.profile
        if value is None:
            self._raw.setText("S = —  (нет данных)")
            for _, indicator, state in self._rows:
                indicator.set_color("lost")
                state.setText("—")
            self._last = None
            return
        self._raw.setText(f"S = 0x{value:02X}   {value:08b}")
        for sensor_state, (_, indicator, state) in zip(profile.sensor_states(value), self._rows):
            sensor = sensor_state.sensor
            if sensor_state.on:
                indicator.set_color("alarm" if sensor.alarm else "on")
            else:
                indicator.set_color("off")
            state.setText(sensor_state.text)
        if self._last is not None and value != self._last:
            self._record(profile, self._last, value)
        self._last = value

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
