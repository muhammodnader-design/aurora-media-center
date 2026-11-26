"""Small volume overlay shown briefly when the level changes."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar


class VolumeOSD(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("volumeOsd")
        self.setFixedSize(250, 62)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)
        self.icon = QLabel("\U0001F50A")
        self.icon.setObjectName("volumeIcon")
        self.bar = QProgressBar()
        self.bar.setObjectName("volumeBar")
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.value = QLabel("0%")
        self.value.setObjectName("volumeValue")
        row.addWidget(self.icon)
        row.addWidget(self.bar, 1)
        row.addWidget(self.value)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_level(self, level: int):
        level = max(0, min(100, int(level)))
        if level == 0:
            icon = "\U0001F507"
        elif level < 50:
            icon = "\U0001F509"
        else:
            icon = "\U0001F50A"
        self.icon.setText(icon)
        self.value.setText(f"{level}%")
        self.bar.setValue(level)
        self.reposition()
        self.show()
        self.raise_()
        self._timer.start(1400)

    def reposition(self):
        parent = self.parentWidget()
        if parent is not None:
            x = (parent.width() - self.width()) // 2
            y = max(20, parent.height() - self.height() - 170)
            self.move(x, y)
