"""Vertical category menu: selected item large and glowing, neighbors fade,
and the whole list slides smoothly when the selection changes."""
from PySide6.QtCore import (Qt, Signal, Property, QPropertyAnimation,
                            QEasingCurve, QSize)
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtWidgets import QWidget, QSizePolicy


class CategoryMenu(QWidget):
    categoryClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._cats = []          # list of (icon, label)
        self._selected = 0
        self._pos = 0.0          # animated float selection position
        self._accent = QColor("#35e0ff")
        self._dim = QColor("#5d7f92")
        self._sel_size = 40
        self._norm_size = 23
        self._spacing = 80
        self._anim = QPropertyAnimation(self, b"position", self)
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    # ---- QSS-editable properties ----
    def _get_pos(self):
        return self._pos

    def _set_pos(self, v):
        self._pos = v
        self.update()

    position = Property(float, _get_pos, _set_pos)
    accentColor = Property(QColor, lambda s: s._accent,
                           lambda s, v: (setattr(s, "_accent", QColor(v)), s.update()))
    dimColor = Property(QColor, lambda s: s._dim,
                        lambda s, v: (setattr(s, "_dim", QColor(v)), s.update()))
    selectedFontSize = Property(int, lambda s: s._sel_size,
                                lambda s, v: (setattr(s, "_sel_size", v), s.update()))
    normalFontSize = Property(int, lambda s: s._norm_size,
                              lambda s, v: (setattr(s, "_norm_size", v), s.update()))
    rowSpacing = Property(int, lambda s: s._spacing,
                          lambda s, v: (setattr(s, "_spacing", v), s.update()))

    # ---- API ----
    def set_categories(self, cats, keep=0):
        self._cats = [(c["icon"], c["label"]) for c in cats]
        self._selected = max(0, min(keep, len(self._cats) - 1))
        self._anim.stop()
        self._pos = float(self._selected)
        self.updateGeometry()
        self.update()

    def minimumSizeHint(self):
        return QSize(260, int(self._spacing * 3))

    def sizeHint(self):
        rows = max(3, len(self._cats))
        return QSize(330, int(self._spacing * (rows + 1)))

    @property
    def selected(self):
        return self._selected

    def select(self, index, animate=True):
        if not self._cats:
            return
        index = max(0, min(index, len(self._cats) - 1))
        if index == self._selected and animate:
            return
        self._selected = index
        self._anim.stop()
        if animate:
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(float(index))
            self._anim.start()
        else:
            self._pos = float(index)
            self.update()

    def _step(self):
        """Row distance, compressed so the whole list fits when space is tight."""
        rows = len(self._cats)
        if rows <= 1:
            return float(self._spacing)
        room = max(60.0, self.height() / 2.0 - self._sel_size - 12)
        return min(float(self._spacing), room / (rows - 1))

    # ---- painting ----
    def paintEvent(self, _event):
        if not self._cats:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        cy = self.height() / 2.0
        step = self._step()
        white = QColor("#eef8fc")
        for i, (icon, label) in enumerate(self._cats):
            off = i - self._pos
            y = cy + off * step
            if y < -step or y > self.height() + step:
                continue
            d = abs(off)
            t = max(0.0, 1.0 - d)                 # 1 at focus, 0 one step away
            size = self._norm_size + (self._sel_size - self._norm_size) * t
            alpha = max(0.16, 1.0 - 0.42 * d)
            font = QFont(self.font())
            font.setPixelSize(int(round(size)))
            font.setWeight(QFont.DemiBold if t > 0.5 else QFont.Normal)
            p.setFont(font)
            rect = self.rect().adjusted(26, 0, -8, 0)
            from PySide6.QtCore import QRectF
            text_rect = QRectF(rect.left(), y - size, rect.width(), size * 2)
            text = f"{icon}  {label}"
            if t > 0.35:  # soft glow behind the selected label
                glow = QColor(self._accent)
                glow.setAlpha(int(70 * t))
                p.setPen(glow)
                for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2)):
                    p.drawText(text_rect.translated(dx, dy),
                               Qt.AlignVCenter | Qt.AlignLeft, text)
            color = QColor(
                int(self._dim.red() + (white.red() - self._dim.red()) * t),
                int(self._dim.green() + (white.green() - self._dim.green()) * t),
                int(self._dim.blue() + (white.blue() - self._dim.blue()) * t),
            )
            color.setAlphaF(alpha)
            p.setPen(color)
            p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()

    # ---- mouse ----
    def _index_at(self, y):
        cy = self.height() / 2.0
        return int(round(self._pos + (y - cy) / self._step()))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._cats:
            i = self._index_at(event.position().y())
            if 0 <= i < len(self._cats):
                self.categoryClicked.emit(i)

    def wheelEvent(self, event):
        if not self._cats:
            return
        step = -1 if event.angleDelta().y() > 0 else 1
        i = max(0, min(self._selected + step, len(self._cats) - 1))
        if i != self._selected:
            self.categoryClicked.emit(i)
