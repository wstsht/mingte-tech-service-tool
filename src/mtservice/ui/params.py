from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QWidget

from ..devices import Command


class ParamEditor(QWidget):
    def __init__(self, command: Command, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.command = command
        self._fields: dict[str, QComboBox] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for param in command.params:
            field = QComboBox()
            for label, value in param.choices:
                field.addItem(label, value)
            field.setCurrentIndex(field.findData(param.default))
            field.setToolTip(param.title)
            self._fields[param.key] = field
            layout.addWidget(field)

    def values(self) -> dict[str, int]:
        return {key: field.currentData() for key, field in self._fields.items()}

    def set_values(self, values: dict[str, int]) -> None:
        for key, value in values.items():
            field = self._fields.get(key)
            if field is not None and field.findData(value) >= 0:
                field.setCurrentIndex(field.findData(value))
