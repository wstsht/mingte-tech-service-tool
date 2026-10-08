import pytest
from PySide6.QtGui import QColor

from mtservice.ui.colors import ACTIVE, ERROR, NOTE


def luminance(color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    q = QColor(color)
    return 0.2126 * channel(q.red()) + 0.7152 * channel(q.green()) + 0.0722 * channel(q.blue())


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("key", list(ACTIVE))
def test_active_rows_are_readable(key):
    background, text = ACTIVE[key]
    assert contrast(background, text) >= 4.5


@pytest.mark.parametrize("dark, base", [(False, "#ffffff"), (True, "#1e1e1e"), (True, "#2d2d2d")])
def test_log_colors_are_readable(dark, base):
    assert contrast(NOTE[dark], base) >= 4.5
    assert contrast(ERROR[dark], base) >= 4.5
