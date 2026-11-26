"""Modal quit confirmation, styled by the shared QSS."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton)


class QuitDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("quitDialog")
        self.setWindowTitle("Quit Aurora")
        self.setModal(True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setFixedSize(440, 190)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 24)
        root.setSpacing(22)

        label = QLabel("Are you sure you want to quit?")
        label.setObjectName("quitLabel")
        label.setAlignment(Qt.AlignCenter)
        root.addWidget(label)

        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch(1)
        yes = QPushButton("Yes")
        yes.setObjectName("quitYes")
        yes.setCursor(Qt.PointingHandCursor)
        yes.clicked.connect(self.accept)
        no = QPushButton("No")
        no.setObjectName("quitNo")
        no.setCursor(Qt.PointingHandCursor)
        no.setDefault(True)
        no.clicked.connect(self.reject)
        row.addWidget(yes)
        row.addWidget(no)
        row.addStretch(1)
        root.addLayout(row)
