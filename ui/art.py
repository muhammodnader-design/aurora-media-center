"""Generated tile artwork: hue-based gradient card with an icon.

If an item has an extracted icon (game executables on Windows), that image
is drawn instead of the emoji glyph.
"""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPixmap, QPainter, QLinearGradient, QColor, QFont, QPainterPath


def art_pixmap(hue: float, icon: str, w: int, h: int, radius: int = 18,
               icon_path: str = "") -> QPixmap:
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setRenderHint(QPainter.TextAntialiasing)

    hfrac = (hue % 360) / 360.0
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0.0, QColor.fromHsvF(hfrac, 0.60, 0.62))
    grad.setColorAt(1.0, QColor.fromHsvF(hfrac, 0.78, 0.24))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.fillPath(path, grad)

    # soft top sheen
    sheen = QLinearGradient(0, 0, 0, h * 0.5)
    sheen.setColorAt(0.0, QColor(255, 255, 255, 36))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path, sheen)

    drawn = False
    if icon_path:
        icon_pm = QPixmap(icon_path)
        if not icon_pm.isNull():
            target = int(h * 0.52)
            scaled = icon_pm.scaled(target, target, Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation)
            p.drawPixmap(int((w - scaled.width()) / 2),
                         int(h * 0.5 - scaled.height() / 2 - h * 0.05),
                         scaled)
            drawn = True
    if not drawn:
        font = QFont()
        font.setFamilies(["Segoe UI Emoji", "Noto Color Emoji", "Apple Color Emoji",
                          "Symbola", "DejaVu Sans", "Noto Sans"])
        font.setPixelSize(int(h * 0.38))
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(QRectF(0, -h * 0.06, w, h), Qt.AlignCenter, icon)
    p.end()
    return pm
