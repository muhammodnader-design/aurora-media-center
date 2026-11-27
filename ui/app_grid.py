"""Scrollable icon grid for Quick Launch.

Painted directly for the same 10-foot look as the rest of Aurora: section
headers, focus glow, arrow-key navigation, mouse selection, and a slim
scroll indicator that only appears when there is more content than space.
"""
from PySide6.QtCore import (Qt, Signal, QRect, QRectF, QPropertyAnimation,
                            QEasingCurve, Property)
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import QWidget

TILE_W = 176
TILE_H = 176
GAP = 22
HEADER_H = 42
SECTION_GAP = 24
PAD = 4


class AppGrid(QWidget):
    activated = Signal(dict)            # Enter, double-click, or second click
    selectionChanged = Signal(object)   # app dict, or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self._sections = []
        self._flat = []
        self._rects = []
        self._headers = []
        self._pinned_ids = set()
        self._focus = 0
        self._scroll = 0.0
        self._content_h = 0
        self._hit_rects = []
        self._accent = QColor("#35e0ff")
        self._icon_cache = {}
        self._fallback_cache = {}
        self._anim = QPropertyAnimation(self, b"scrollOffset", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    # ---- QSS-editable ---
    def _get_scroll(self):
        return self._scroll

    def _set_scroll(self, value):
        high = max(0.0, self._content_h - self.height())
        value = max(0.0, min(float(value), high))
        if abs(value - self._scroll) < 0.5:
            return
        self._scroll = value
        self.update()

    scrollOffset = Property(float, _get_scroll, _set_scroll)
    accentColor = Property(QColor, lambda s: s._accent,
                           lambda s, v: (setattr(s, "_accent", QColor(v)),
                                         s.update()))

    # ---- data ----
    def set_sections(self, sections, keep_id=None, pinned_ids=None):
        """sections: list of (label, [app dicts]). Empty sections are dropped."""
        if keep_id is None:
            keep = self.current_app()
            keep_id = keep.get("id") if keep else None
        self._pinned_ids = set(pinned_ids or ())
        self._sections = [(label, list(apps)) for label, apps in sections
                          if apps]
        self._layout()
        self._anim.stop()
        self._scroll = 0.0
        index = 0
        if keep_id:
            index = next((i for i, app in enumerate(self._flat)
                          if app.get("id") == keep_id), 0)
        self._focus = min(index, max(0, len(self._flat) - 1))
        self._ensure_visible(animate=False)
        self.update()
        self.selectionChanged.emit(self.current_app())

    def current_app(self):
        if 0 <= self._focus < len(self._flat):
            return self._flat[self._focus]
        return None

    def focus_count(self):
        return len(self._flat)

    def focus_id(self):
        app = self.current_app()
        return app.get("id") if app else None

    def refresh(self):
        """Repaint after an icon file appears without rebuilding sections."""
        self._icon_cache.clear()
        self.update()

    # ---- layout ----
    def _columns(self):
        width = max(0, self.width() - 2 * PAD)
        step = TILE_W + GAP
        return max(1, (width + GAP) // step) if width else 1

    def _layout(self):
        self._flat = []
        self._rects = []
        self._headers = []
        cols = self._columns()
        step = TILE_W + GAP
        y = 0
        for label, apps in self._sections:
            if not apps:
                continue
            self._headers.append(
                (label, QRect(PAD, y, max(0, self.width() - 2 * PAD), HEADER_H)))
            y += HEADER_H
            for start in range(0, len(apps), cols):
                row = apps[start:start + cols]
                for col, app in enumerate(row):
                    self._flat.append(app)
                    self._rects.append(
                        QRect(PAD + col * step, y, TILE_W, TILE_H))
                y += TILE_H + GAP
            y += SECTION_GAP
        self._content_h = max(0, y - SECTION_GAP)
        self._focus = min(self._focus, max(0, len(self._flat) - 1))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout()
        self._ensure_visible(animate=False)
        self.update()

    # ---- focus movement ----
    def move_focus(self, dx: int, dy: int):
        count = len(self._flat)
        if not count:
            return
        if dx:
            self._set_focus(self._focus + dx)
            return
        if not dy:
            return
        current = self._rects[self._focus]
        centers = [r.center().y() for r in self._rects]
        if dy < 0:
            bands = [r.bottom() for r in self._rects if r.bottom() <= current.top() + 2]
            if not bands:
                return
            band = max(bands)
            pool = [i for i, r in enumerate(self._rects) if r.bottom() == band]
        else:
            bands = [r.top() for r in self._rects if r.top() >= current.bottom() - 2]
            if not bands:
                return
            band = min(bands)
            pool = [i for i, r in enumerate(self._rects) if r.top() == band]
        target = min(pool, key=lambda i:
                     abs(self._rects[i].center().x() - current.center().x()))
        self._set_focus(target)

    def set_focus(self, index: int):
        self._set_focus(index)

    def move_page(self, direction: int):
        """Move focus up or down by roughly one visible viewport page."""
        if not self._flat:
            return
        rows_per_page = max(1, self.height() // (TILE_H + GAP))
        cols = self._columns()
        step = rows_per_page * cols * (1 if direction > 0 else -1)
        self._set_focus(self._focus + step)

    def _set_focus(self, index: int):
        if not self._flat:
            return
        index = max(0, min(index, len(self._flat) - 1))
        if index == self._focus:
            return
        self._focus = index
        self._ensure_visible()
        self.update()
        self.selectionChanged.emit(self.current_app())

    def activate_focused(self):
        app = self.current_app()
        if app is not None:
            self.activated.emit(app)

    def _ensure_visible(self, animate=True):
        if not self._rects or self._focus >= len(self._rects):
            return
        rect = self._rects[self._focus]
        top = rect.top() - 6
        bottom = rect.bottom() + 6
        target = self._scroll
        view = self.height()
        if top < target:
            target = top
        elif bottom > target + view:
            target = bottom - view
        high = max(0.0, self._content_h - view)
        target = max(0.0, min(target, high))
        self._anim.stop()
        if not animate:
            self._set_scroll(target)
        elif abs(target - self._scroll) > 1:
            self._anim.setStartValue(self._scroll)
            self._anim.setEndValue(target)
            self._anim.start()

    # ---- painting ----
    def _fallback(self, app):
        hue = int(float(app.get("hue", 200))) % 360
        key = (hue, app.get("title", "")[:1].upper())
        pm = self._fallback_cache.get(key)
        if pm is None:
            from .art import art_pixmap
            pm = art_pixmap(hue, key[1] or "•", 96, 96, 20)
            self._fallback_cache[key] = pm
        return pm

    def _icon(self, app):
        path = str(app.get("icon_abs") or "")
        if not path:
            return self._fallback(app)
        key = (app.get("id"), path)
        if key in self._icon_cache:
            return self._icon_cache[key]
        from PySide6.QtGui import QPixmap
        pm = QPixmap(path)
        if pm.isNull():
            pm = self._fallback(app)
        self._icon_cache[key] = pm
        return pm

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.TextAntialiasing)
        self._hit_rects = []
        p.translate(0, -int(self._scroll))

        if not self._sections:
            p.setPen(QColor("#557588"))
            font = QFont(self.font())
            font.setPixelSize(17)
            p.setFont(font)
            p.drawText(QRect(0, 0, self.width(), self.height()),
                       Qt.AlignCenter,
                       "No apps yet — press F2 to add one, or enable "
                       "app discovery in Settings (F3).")
            p.end()
            return

        header_font = QFont(self.font())
        header_font.setPixelSize(14)
        header_font.setWeight(QFont.DemiBold)
        header_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.8)

        for label, rect in self._headers:
            if rect.bottom() < self._scroll - 2:
                continue
            if rect.top() > self._scroll + self.height():
                continue
            p.setFont(header_font)
            p.setPen(QColor(125, 243, 225, 215))
            p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, label.upper())
            line_x = rect.left() + p.fontMetrics().horizontalAdvance(
                label.upper()) + 18
            p.setPen(QPen(QColor(53, 224, 255, 36), 1))
            p.drawLine(line_x, rect.center().y(), rect.right(),
                       rect.center().y())

        label_font = QFont(self.font())
        label_font.setPixelSize(15)
        label_font.setWeight(QFont.DemiBold)

        badge_font = QFont(self.font())
        badge_font.setPixelSize(12)

        for index, rect in enumerate(self._rects):
            view_rect = rect.translated(0, -int(self._scroll))
            if view_rect.bottom() < -4 or view_rect.top() > self.height() + 4:
                continue
            app = self._flat[index]
            focused = index == self._focus
            self._hit_rects.append((index, view_rect))

            card = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
            if focused:
                p.setBrush(QColor(18, 58, 74, 240))
                p.setPen(QPen(QColor(self._accent).lighter(105), 2))
            else:
                p.setBrush(QColor(11, 34, 49, 195))
                p.setPen(QPen(QColor("#173c4d"), 1))
            p.drawRoundedRect(card, 18, 18)

            if focused:
                for width, alpha in ((12, 22), (7, 48), (3, 150)):
                    glow = QColor(self._accent)
                    glow.setAlpha(alpha)
                    p.setPen(QPen(glow, width))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(card.adjusted(1, 1, -1, -1), 18, 18)

            if app.get("id") in self._pinned_ids:
                p.setFont(badge_font)
                p.setPen(QColor(125, 243, 225, 210 if focused else 140))
                p.drawText(QRect(rect.right() - 28, rect.top() + 8, 20, 18),
                           Qt.AlignCenter, "★")

            icon_size = 96
            icon_rect = QRect(rect.x() + (rect.width() - icon_size) // 2,
                              rect.y() + 18, icon_size, icon_size)
            pm = self._icon(app)
            icon_pm = pm.scaled(icon_size, icon_size, Qt.KeepAspectRatio,
                                Qt.SmoothTransformation)
            p.drawPixmap(
                icon_rect.x() + (icon_rect.width() - icon_pm.width()) // 2,
                icon_rect.y() + (icon_rect.height() - icon_pm.height()) // 2,
                icon_pm)

            p.setFont(label_font)
            p.setPen(QColor(238, 248, 252, 242 if focused else 200))
            text_rect = QRect(rect.x() + 10, rect.bottom() - 42,
                              rect.width() - 20, 30)
            metrics = p.fontMetrics()
            p.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter,
                       metrics.elidedText(app.get("title", ""),
                                          Qt.ElideRight,
                                          text_rect.width()))

        if self._content_h > self.height():
            track = QRect(self.width() - 5, 6, 3, self.height() - 12)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(29, 74, 94, 90))
            p.drawRoundedRect(track, 2, 2)
            span = max(1, self._content_h)
            ratio = self.height() / span
            thumb_h = max(24, int(track.height() * ratio))
            travel = track.height() - thumb_h
            high = max(1, self._content_h - self.height())
            y = track.top() + int(travel * (self._scroll / high))
            p.setBrush(QColor(53, 224, 255, 130))
            p.drawRoundedRect(QRect(track.x(), y, 3, thumb_h), 2, 2)
        p.end()

    # ---- mouse ----
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        for index, rect in self._hit_rects:
            if rect.contains(pos.toPoint()):
                if index == self._focus:
                    self.activated.emit(self._flat[index])
                else:
                    self._set_focus(index)
                return

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        for _index, rect in self._hit_rects:
            if rect.contains(pos.toPoint()):
                self.activate_focused()
                return

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not delta:
            return
        self._anim.stop()
        self._set_scroll(self._scroll - delta / 3.0)
        event.accept()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Left:
            self.move_focus(-1, 0)
        elif key == Qt.Key_Right:
            self.move_focus(1, 0)
        elif key == Qt.Key_Up:
            self.move_focus(0, -1)
        elif key == Qt.Key_Down:
            self.move_focus(0, 1)
        elif key == Qt.Key_Home:
            self.set_focus(0)
        elif key == Qt.Key_End:
            self.set_focus(max(0, self.focus_count() - 1))
        elif key == Qt.Key_PageUp:
            self.move_page(-1)
        elif key == Qt.Key_PageDown:
            self.move_page(1)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self.activate_focused()
        else:
            super().keyPressEvent(event)
