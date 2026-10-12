"""uiscale.py - DPI-aware skalovani GUI z jednoho zakladniho fontu (prevzato z drone).

Vsechny rozmery (sirky sloupcu, vysky radku) se odvozuji z QFontMetrics zakladniho
fontu, takze GUI vypada konzistentne na ruznych DPI.
"""

from PySide6 import QtGui, QtWidgets

BASE_POINT_SIZE = 10


def apply_base_font(app: QtWidgets.QApplication) -> None:
    """Pripni zakladni velikost fontu na celou aplikaci (volat PRED tvorbou widgetu)."""
    f = app.font()
    f.setPointSize(BASE_POINT_SIZE)
    app.setFont(f)


def _fm() -> QtGui.QFontMetrics:
    return QtGui.QFontMetrics(QtWidgets.QApplication.font())


def char_w() -> int:
    return max(1, _fm().averageCharWidth())


def col_w(chars: float) -> int:
    """Sirka v pixelech pro ~`chars` znaku."""
    return int(char_w() * chars)


def row_h(factor: float = 1.0) -> int:
    """Vyska radku (nasobek vysky fontu)."""
    return int(_fm().height() * factor)


def heading_font() -> QtGui.QFont:
    f = QtWidgets.QApplication.font()
    f.setPointSize(int(BASE_POINT_SIZE * 1.3))
    f.setBold(True)
    return f


def note_font() -> QtGui.QFont:
    f = QtWidgets.QApplication.font()
    f.setPointSize(int(BASE_POINT_SIZE * 0.9))
    return f
