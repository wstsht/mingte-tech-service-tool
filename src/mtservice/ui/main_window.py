from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..devices import PROFILES, Profile
from ..transport import available_ports
from .commands_panel import CommandsPanel
from .log_panel import LogPanel
from .script_panel import ScriptPanel
from .sensors_panel import SensorsPanel
from .session import EMULATOR, Session

BAUDRATES = ("9600", "19200", "38400", "57600", "115200")
AUTO = ""


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"Mingte Tech Service Tool {__version__}")
        self.settings = settings or QSettings("mingte-tech-service-tool", "mtservice")
        self.session = Session(self)

        self.port = QComboBox()
        self.port.setEditable(True)
        self.port.setMinimumWidth(220)
        self.port.setMaximumWidth(360)
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self.refresh_ports)

        self.baud = QComboBox()
        self.baud.setEditable(True)
        self.baud.addItems(BAUDRATES)
        self.baud.setValidator(QIntValidator(300, 4_000_000, self))

        self.model = QComboBox()
        self.model.addItem("Авто", AUTO)
        for profile in PROFILES.values():
            self.model.addItem(profile.model, profile.key)
        self.model.activated.connect(self._model_picked)

        self.connect_button = QPushButton("Подключить")
        self.connect_button.clicked.connect(self._toggle_connection)

        bar = QHBoxLayout()
        for label, widget in (("Порт", self.port), ("Скорость", self.baud), ("Модель", self.model)):
            bar.addWidget(QLabel(label))
            bar.addWidget(widget)
            if widget is self.port:
                bar.addWidget(refresh)
            bar.addSpacing(12)
        bar.addWidget(self.connect_button)
        bar.addStretch(1)

        self.commands = CommandsPanel(self.session)
        self.sensors = SensorsPanel(self.session)
        self.scripts = ScriptPanel(self.session)
        self.log = LogPanel(self.session)

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self.commands)
        top.addWidget(self.sensors)
        top.addWidget(self.scripts)
        top.setSizes([330, 330, 480])
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(top)
        self.splitter.addWidget(self.log)
        self.splitter.setSizes([520, 240])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(bar)
        layout.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

        self.state = QLabel("Нет подключения")
        self.statusBar().addPermanentWidget(self.state)
        self.session.message.connect(lambda text: self.statusBar().showMessage(text, 10000))
        self.session.connection_changed.connect(self._on_connection)
        self.session.profile_changed.connect(self._on_profile)

        self.refresh_ports()
        self._restore()

    def refresh_ports(self) -> None:
        current = self.port.currentData() or self.port.currentText()
        self.port.clear()
        for device, description in available_ports():
            label = f"{device} — {description}" if description and description != "n/a" else device
            self.port.addItem(label, device)
        for profile in PROFILES.values():
            self.port.addItem(f"Эмулятор {profile.model}", EMULATOR + profile.key)
        index = self.port.findData(current)
        if index >= 0:
            self.port.setCurrentIndex(index)

    def selected_port(self) -> str:
        text = self.port.currentText().strip()
        index = self.port.findText(text)
        if index >= 0 and self.port.itemData(index):
            return self.port.itemData(index)
        return text

    def _model_picked(self) -> None:
        key = self.model.currentData()
        if key:
            self.baud.setCurrentText(str(PROFILES[key].baudrate))
            self.session.set_profile(PROFILES[key])

    def _toggle_connection(self) -> None:
        if self.session.connected:
            self.session.close()
            return
        port = self.selected_port()
        if not port:
            self.statusBar().showMessage("Укажите порт", 5000)
            return
        baudrate = int(self.baud.currentText() or 0)
        if baudrate <= 0:
            self.statusBar().showMessage("Укажите скорость", 5000)
            return
        self.session.open(port, baudrate, self.model.currentData() or None)

    def _on_connection(self, connected: bool) -> None:
        self.connect_button.setText("Отключить" if connected else "Подключить")
        for widget in (self.port, self.baud, self.model):
            widget.setEnabled(not connected)
        if connected:
            self._on_profile(self.session.profile)
        else:
            self.state.setText("Нет подключения")

    def _on_profile(self, profile: Profile) -> None:
        if self.session.connected:
            index = self.port.findData(self.session.port)
            port = self.port.itemText(index) if index >= 0 else self.session.port
            self.state.setText(f"{port} · {profile.model}")

    def _restore(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1280, 820)
        port = self.settings.value("port", "")
        index = self.port.findData(port)
        if index >= 0:
            self.port.setCurrentIndex(index)
        elif port:
            self.port.setEditText(port)
        self.baud.setCurrentText(str(self.settings.value("baudrate", "38400")))
        index = self.model.findData(self.settings.value("model", AUTO))
        self.model.setCurrentIndex(max(index, 0))
        if self.model.currentData():
            self.session.set_profile(PROFILES[self.model.currentData()])

    def closeEvent(self, event) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("port", self.selected_port())
        self.settings.setValue("baudrate", self.baud.currentText())
        self.settings.setValue("model", self.model.currentData())
        self.scripts.stop()
        self.session.close()
        super().closeEvent(event)
