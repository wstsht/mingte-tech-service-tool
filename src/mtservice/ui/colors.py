from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

ACTIVE = {
    (False, False): ("#e2f3e5", "#1f6b33"),
    (False, True): ("#1d4a2a", "#c3f2cf"),
    (True, False): ("#fbe1de", "#a8261b"),
    (True, True): ("#5c1f1a", "#ffd2cc"),
}
NOTE = {False: "#5b6472", True: "#9aa3ae"}
ERROR = {False: "#c0392b", True: "#ff8a80"}


def is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.ColorRole.Base).lightness() < 128


def active_colors(alarm: bool, dark: bool) -> tuple[QColor, QColor]:
    background, text = ACTIVE[(alarm, dark)]
    return QColor(background), QColor(text)
