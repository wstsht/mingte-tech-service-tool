from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QSpinBox, QWidget

from ..devices import Command


class ParamEditor(QWidget):
    """Поля ввода для параметров команды: список выбора или число."""

    def __init__(self, command: Command, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.command = command
        self._fields: dict[str, QComboBox | QSpinBox] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for param in command.params:
            if param.choices:
                field = QComboBox()
                for label, value in param.choices:
                    field.addItem(label, value)
                field.setCurrentIndex(field.findData(param.default))
            else:
                field = QSpinBox()
                field.setRange(param.minimum, param.maximum)
                field.setValue(param.default)
            field.setToolTip(param.title)
            self._fields[param.key] = field
            layout.addWidget(field)

    def values(self) -> dict[str, int]:
        result = {}
        for key, field in self._fields.items():
            result[key] = field.currentData() if isinstance(field, QComboBox) else field.value()
        return result

    def set_values(self, values: dict[str, int]) -> None:
        for key, value in values.items():
            field = self._fields.get(key)
            if isinstance(field, QComboBox):
                index = field.findData(value)
                if index >= 0:
                    field.setCurrentIndex(index)
            elif isinstance(field, QSpinBox):
                field.setValue(value)
