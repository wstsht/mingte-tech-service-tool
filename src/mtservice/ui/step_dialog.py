from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..devices import Profile
from ..scripts import CommandStep, PauseStep, RepeatStep, Step, WaitStep
from .params import ParamEditor

TITLES = {
    CommandStep: "Команда",
    PauseStep: "Пауза",
    RepeatStep: "Повтор",
    WaitStep: "Ожидание датчика",
}


def _spin(minimum: int, maximum: int, value: int, suffix: str = "") -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    spin.setSuffix(suffix)
    spin.setGroupSeparatorShown(True)
    return spin


class StepDialog(QDialog):
    def __init__(self, step: Step, profile: Profile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLES[type(step)])
        self.step = step
        self.profile = profile
        self._form = QFormLayout()

        if isinstance(step, CommandStep):
            self._command = QComboBox()
            for command in profile.commands:
                self._command.addItem(command.title, command.key)
            index = self._command.findData(step.command)
            self._command.setCurrentIndex(max(index, 0))
            self._params: ParamEditor | None = None
            self._form.addRow("Команда", self._command)
            self._command.currentIndexChanged.connect(self._rebuild_params)
            self._rebuild_params()
            if self._params:
                self._params.set_values(step.values)
        elif isinstance(step, PauseStep):
            self._ms = _spin(0, 3_600_000, step.ms, " мс")
            self._form.addRow("Длительность", self._ms)
        elif isinstance(step, RepeatStep):
            self._times = _spin(0, 10_000_000, step.times)
            self._times.setSpecialValueText("без конца")
            self._form.addRow("Сколько раз", self._times)
        elif isinstance(step, WaitStep):
            self._sensor = QComboBox()
            for sensor in profile.sensors:
                self._sensor.addItem(f"b{sensor.bit}  {sensor.title}", sensor.bit)
            self._sensor.setCurrentIndex(max(self._sensor.findData(step.bit), 0))
            self._state = QComboBox()
            self._sensor.currentIndexChanged.connect(lambda: self._fill_states(True))
            self._fill_states(step.state)
            self._timeout = _spin(100, 3_600_000, step.timeout_ms, " мс")
            self._form.addRow("Датчик", self._sensor)
            self._form.addRow("Состояние", self._state)
            self._form.addRow("Не дольше", self._timeout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self._form)
        layout.addWidget(buttons)

    def _rebuild_params(self) -> None:
        if self._params is not None:
            self._form.removeRow(1)
            self._params = None
        command = self.profile.command(self._command.currentData())
        if command.params:
            self._params = ParamEditor(command)
            self._form.addRow("Параметры", self._params)

    def _fill_states(self, state: bool) -> None:
        sensor = next(s for s in self.profile.sensors if s.bit == self._sensor.currentData())
        self._state.clear()
        self._state.addItem(sensor.on, True)
        self._state.addItem(sensor.off, False)
        self._state.setCurrentIndex(0 if state else 1)

    def result_step(self) -> Step:
        step = self.step
        if isinstance(step, CommandStep):
            values = self._params.values() if self._params else {}
            return CommandStep(self._command.currentData(), values)
        if isinstance(step, PauseStep):
            return PauseStep(self._ms.value())
        if isinstance(step, RepeatStep):
            return RepeatStep(self._times.value(), step.steps)
        return WaitStep(self._sensor.currentData(), self._state.currentData(), self._timeout.value())
