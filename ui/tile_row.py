"""Horizontal tile row: focused tile scales up with an accent glow border,
the row slides smoothly, and tiles are clickable (click again to play)."""
from PySide6.QtCore import Qt, Signal, Property, QPropertyAnimation, QEasingCurve, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import QWidget

from .art import art_pixmap


class TileRow(QWidget):
    tileClicked = Signal(int)     # clicked tile index (already focused -> play)
    focusChanged = Signal(int)    # focused tile index changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self._items = []
        self._focus = 0
        self._pos = 0.0
        self._accent = QColor("#35e0ff")
        self._tw = 210
        self._th = 280
        self._spacing = 34
        self._radius = 18
        self._art_cache = {}
        self._hit_rects = []
        self._anim = QPropertyAnimation(self, b"position", self)
        self._anim.setDuration(240)
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
    tileWidth = Property(int, lambda s: s._tw, lambda s, v: s._resize_prop("_tw", v))
    tileHeight = Property(int, lambda s: s._th, lambda s, v: s._resize_prop("_th", v))
    tileSpacing = Property(int, lambda s: s._spacing,
                           lambda s, v: (setattr(s, "_spacing", v), s.update()))
    cornerRadius = Property(int, lambda s: s._radius,
                            lambda s, v: s._resize_prop("_radius", v))

    def _resize_prop(self, name, value):
        setattr(self, name, value)
        self._art_cache.clear()
        self.update()

    # ---- API ----
    def set_items(self, items):
        self._items = items
        self._focus = 0
        self._anim.stop()
        self._pos = 0.0
        self.update()

    @property
    def focus_index(self):
        return self._focus

    def move_focus(self, delta):
        self.set_focus(self._focus + delta)

    def set_focus(self, index, animate=True):
        if not self._items:
            return
        index = max(0, min(index, len(self._items) - 1))
        if index == self._focus:
            return
        self._focus = index
        self._anim.stop()
        if animate:
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(float(index))
            self._anim.start()
        else:
            self._pos = float(index)
            self.update()
        self.focusChanged.emit(index)

    def _art(self, item):
        key = (item["hue"], item["icon"], item.get("art", ""))
        pm = self._art_cache.get(key)
        if pm is None:
            pm = art_pixmap(item["hue"], item["icon"], self._tw, self._th,
                            self._radius, icon_path=item.get("art", ""))
            self._art_cache[key] = pm
        return pm

    # ---- painting ----
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.TextAntialiasing)
        self._hit_rects = []
        w, h = self.width(), self.height()
        if not self._items:
            p.setPen(QColor("#557588"))
            font = QFont(self.font())
            font.setPixelSize(17)
            p.setFont(font)
            p.drawText(self.rect(), Qt.AlignCenter,
                       "No items here yet — add folders in Settings (F3).")
            p.end()
            return

        cy = h / 2.0
        step = self._tw + self._spacing
        for i, item in enumerate(self._items):
            off = i - self._pos
            cx = w / 2.0 + off * step
            if cx < -step or cx > w + step:
                continue
            d = abs(off)
            t = max(0.0, 1.0 - d)
            scale = 1.0 + 0.16 * t
            tw, th = self._tw * scale, self._th * scale
            rect = QRectF(cx - tw / 2, cy - th / 2, tw, th)
            self._hit_rects.append((i, rect))
            p.save()
            p.setOpacity(max(0.30, 1.0 - 0.35 * d))
            p.drawPixmap(rect, self._art(item), QRectF(0, 0, self._tw, self._th))
            # title inside the tile, near the bottom
            font = QFont(self.font())
            font.setPixelSize(int(15 * scale))
            font.setWeight(QFont.DemiBold)
            p.setFont(font)
            p.setPen(QColor(255, 255, 255, 235))
            title_rect = QRectF(rect.left() + 10, rect.bottom() - 44 * scale,
                                rect.width() - 20, 34 * scale)
            metrics = p.fontMetrics()
            p.drawText(title_rect, Qt.AlignHCenter | Qt.AlignVCenter,
                       metrics.elidedText(item["title"], Qt.ElideRight,
                                          int(title_rect.width())))
            p.restore()
            if t > 0.02:  # accent glow border on the focused tile
                for width, alpha in ((10, 26), (6, 60), (2.5, 200)):
                    glow = QColor(self._accent)
                    glow.setAlpha(int(alpha * t))
                    pen = QPen(glow, width)
                    p.setPen(pen)
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(rect.adjusted(1, 1, -1, -1),
                                      self._radius * scale, self._radius * scale)
        p.end()

    # ---- mouse ----
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        for i, rect in self._hit_rects:
            if rect.contains(pos):
                self.tileClicked.emit(i)
                return

    def wheelEvent(self, event):
        if not self._items:
            return
        step = -1 if event.angleDelta().y() > 0 else 1
        self.move_focus(step)
