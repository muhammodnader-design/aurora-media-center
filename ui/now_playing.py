"""Bottom 'now playing' overlay bar. The main window slides it up/down."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QLabel,
                               QProgressBar, QPushButton)


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class NowPlayingBar(QFrame):
    seekRequested = Signal(int)     # seconds, +/-
    skipRequested = Signal(int)     # queue item, -1 / +1
    toggleRequested = Signal()
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nowPlaying")
        self.setFixedHeight(96)
        self.setFocusPolicy(Qt.NoFocus)
        self.count_mode = False  # slideshow: show "3 / 24" instead of times

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(14)

        self.thumb = QLabel()
        self.thumb.setObjectName("npThumb")
        self.thumb.setFixedSize(72, 72)
        self.thumb.setScaledContents(True)
        root.addWidget(self.thumb)

        middle = QVBoxLayout()
        middle.setSpacing(6)
        self.title = QLabel("")
        self.title.setObjectName("npTitle")
        middle.addWidget(self.title)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self.elapsed = QLabel("0:00")
        self.elapsed.setObjectName("npTime")
        self.progress = QProgressBar()
        self.progress.setObjectName("npProgress")
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.total = QLabel("0:00")
        self.total.setObjectName("npTime")
        progress_row.addWidget(self.elapsed)
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.total)
        middle.addLayout(progress_row)
        root.addLayout(middle, 1)

        def make_button(text, slot, tip):
            b = QPushButton(text)
            b.setObjectName("npButton")
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            root.addWidget(b)
            return b

        self.prev_btn = make_button("⏮", lambda: self.skipRequested.emit(-1), "Previous item")
        self.back_btn = make_button("-10", lambda: self.seekRequested.emit(-10), "Back 10 seconds")
        self.play_btn = make_button("⏸", self.toggleRequested.emit, "Play / pause (Enter)")
        self.fwd_btn = make_button("+10", lambda: self.seekRequested.emit(10), "Forward 10 seconds")
        self.next_btn = make_button("⏭", lambda: self.skipRequested.emit(1), "Next item")
        self.close_btn = make_button("✕", self.closeRequested.emit, "Close (Esc)")

    def set_media(self, title: str, pixmap: QPixmap):
        self.title.setText(title)
        self.thumb.setPixmap(pixmap)

    def set_state(self, playing: bool, pos: float, dur: float):
        self.play_btn.setText("⏸" if playing else "▶")
        self.progress.setValue(int(pos / dur * 1000) if dur > 0 else 0)
        if self.count_mode:
            self.elapsed.setText(str(int(pos)))
            self.total.setText(str(int(dur)))
        else:
            self.elapsed.setText(fmt_time(pos))
            self.total.setText(fmt_time(dur))
