import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtservice.devices import MT166  # noqa: E402
from mtservice.scripts import CommandStep, RepeatStep, Script  # noqa: E402
from mtservice.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    yield window
    window.close()
    app.processEvents()


def wait_until(app, condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def connect(window, key):
    window.port.setCurrentIndex(window.port.findData(f"emulator:{key}"))
    window.model.setCurrentIndex(0)
    window.connect_button.click()


def test_emulators_are_listed(window):
    assert window.port.findData("emulator:mt163") >= 0
    assert window.port.findData("emulator:mt166") >= 0


def test_model_is_detected_and_sensors_are_polled(app, window):
    connect(window, "mt166")
    assert wait_until(app, lambda: window.session.profile.key == "mt166")
    assert wait_until(app, lambda: window.sensors._last is not None)
    assert window.connect_button.text() == "Отключить"
    window.connect_button.click()
    assert not window.session.connected


def test_script_runs_against_emulator(app, window):
    connect(window, "mt163")
    assert wait_until(app, lambda: window.sensors._last is not None)
    steps = [RepeatStep(2, [CommandStep("insert_front"), CommandStep("retain")])]
    window.scripts.load(Script("mt163", steps))
    window.scripts._run()
    assert window.scripts._runner is not None
    assert wait_until(app, lambda: window.scripts._runner is None)
    assert window.scripts._stats.commands == 4
    assert window.scripts._stats.failures == 0
    assert window.scripts._stats.iterations == 2


def test_raw_frame_goes_to_the_device(app, window):
    connect(window, "mt163")
    assert wait_until(app, lambda: window.sensors._last is not None)
    window.commands._raw_input.setText("31 31")
    window.commands._send_raw()
    assert wait_until(app, lambda: window.sensors._last == 0x71)


def test_sensor_table_follows_the_device(app, window):
    connect(window, "mt166")
    assert wait_until(app, lambda: window.session.profile.key == "mt166")
    table = window.sensors._table
    assert [table.horizontalHeaderItem(i).text() for i in range(2)] == ["Сигнал", "Состояние"]
    assert [table.item(row, 0).text() for row in range(table.rowCount())] == [
        "Накопитель пуст", "Карта у выхода", "Карта в тракте", "Мало карт",
        "Выдача", "Сбор", "Ошибка выдачи", "Автосбор",
    ]
    assert wait_until(app, lambda: table.item(1, 1).text() == "Нет")
    window.session.send(MT166.command("to_bezel").frame())
    assert wait_until(app, lambda: table.item(1, 1).text() == "Да")
