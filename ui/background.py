"""Fullscreen background: dark teal/blue gradient with slowly drifting glows."""
from PySide6.QtCore import Qt, QTimer, Property, QPointF
from PySide6.QtGui import QPainter, QLinearGradient, QRadialGradient, QColor
from PySide6.QtWidgets import QWidget

import math


class GlowBackground(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg_top = QColor("#041019")
        self._bg_bottom = QColor("#0a2436")
        self._glow_a = QColor(45, 212, 191, 30)
        self._glow_b = QColor(59, 130, 246, 26)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    # QSS-editable properties (qproperty-*)
    def _set(self, name, value):
        setattr(self, "_" + name, QColor(value))
        self.update()

    bgTop = Property(QColor, lambda s: s._bg_top, lambda s, v: s._set("bg_top", v))
    bgBottom = Property(QColor, lambda s: s._bg_bottom, lambda s, v: s._set("bg_bottom", v))
    glowA = Property(QColor, lambda s: s._glow_a, lambda s, v: s._set("glow_a", v))
    glowB = Property(QColor, lambda s: s._glow_b, lambda s, v: s._set("glow_b", v))

    def _advance(self):
        self._t += 0.033
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, self._bg_top)
        grad.setColorAt(1.0, self._bg_bottom)
        p.fillRect(self.rect(), grad)

        p.setRenderHint(QPainter.Antialiasing)
        t = self._t
        r = max(w, h) * 0.55
        ax = w * (0.30 + 0.22 * math.sin(t * 0.21))
        ay = h * (0.35 + 0.18 * math.cos(t * 0.13))
        bx = w * (0.72 + 0.20 * math.cos(t * 0.17))
        by = h * (0.68 + 0.20 * math.sin(t * 0.11))
        for center, color in ((QPointF(ax, ay), self._glow_a),
                              (QPointF(bx, by), self._glow_b)):
            rg = QRadialGradient(center, r)
            rg.setColorAt(0.0, color)
            transparent = QColor(color)
            transparent.setAlpha(0)
            rg.setColorAt(1.0, transparent)
            p.fillRect(self.rect(), rg)
        p.end()
