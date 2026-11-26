"""Settings screen: playback options, media folders, privacy toggle."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QListWidget, QSpinBox, QCheckBox,
                               QSlider, QFileDialog, QApplication, QScrollArea,
                               QWidget, QFrame)

from core.scanner import scan_into_library
from core.resume import ResumeStore


class SettingsDialog(QDialog):
    settingsChanged = Signal(dict)

    def __init__(self, root: Path, settings: dict, parent=None):
        super().__init__(parent)
        self.root = root
        self.settings = dict(settings)
        self.settings["scan_folders"] = list(settings["scan_folders"])
        self.setObjectName("settingsDialog")
        self.setWindowTitle("Aurora Settings")
        self.setModal(True)
        self.setMinimumWidth(600)
        self.resize(640, 720)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("settingsContent")
        root_layout = QVBoxLayout(content)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(12)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        title = QLabel("Settings")
        title.setObjectName("settingsTitle")
        root_layout.addWidget(title)

        # ---- playback ----
        section = QLabel("Playback")
        section.setObjectName("settingsSection")
        root_layout.addWidget(section)

        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("Volume"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(settings["volume"])
        self.volume_label = QLabel(f"{settings['volume']}%")
        self.volume.valueChanged.connect(self._on_volume)
        vol_row.addWidget(self.volume, 1)
        vol_row.addWidget(self.volume_label)
        root_layout.addLayout(vol_row)

        slide_row = QHBoxLayout()
        slide_row.addWidget(QLabel("Seconds per picture"))
        self.interval = QSpinBox()
        self.interval.setRange(1, 120)
        self.interval.setValue(settings["slideshow_interval"])
        self.interval.valueChanged.connect(self._emit_changed)
        slide_row.addWidget(self.interval)
        slide_row.addStretch(1)
        self.fullscreen = QCheckBox("Start in fullscreen")
        self.fullscreen.setChecked(bool(settings["start_fullscreen"]))
        self.fullscreen.toggled.connect(self._emit_changed)
        slide_row.addWidget(self.fullscreen)
        root_layout.addLayout(slide_row)

        resume_row = QHBoxLayout()
        self.resume = QCheckBox("Resume playback where I stopped")
        self.resume.setChecked(bool(settings.get("resume_enabled", True)))
        self.resume.toggled.connect(self._emit_changed)
        resume_row.addWidget(self.resume)
        resume_row.addStretch(1)
        resume_row.addWidget(self._button("Clear resume points", self._clear_resume))
        root_layout.addLayout(resume_row)

        # ---- library folders ----
        section = QLabel("Media folders (scanned into data/library.json)")
        section.setObjectName("settingsSection")
        root_layout.addWidget(section)

        self.folder_list = QListWidget()
        self.folder_list.setObjectName("folderList")
        self.folder_list.setFixedHeight(110)
        self._fill_list(self.folder_list, self.settings["scan_folders"])
        root_layout.addWidget(self.folder_list)

        folder_buttons = QHBoxLayout()
        folder_buttons.addWidget(self._button("Add folder…", self._add_folder))
        self.remove_btn = self._button("Remove", self._remove_folder)
        self.scan_btn = self._button("Scan now", self._scan)
        folder_buttons.addWidget(self.remove_btn)
        folder_buttons.addStretch(1)
        folder_buttons.addWidget(self.scan_btn)
        root_layout.addLayout(folder_buttons)

        # ---- privacy ----
        section = QLabel("Privacy")
        section.setObjectName("settingsSection")
        root_layout.addWidget(section)
        self.show_hidden = QCheckBox("Show private items")
        self.show_hidden.setToolTip("Items marked hidden stay out of every category.")
        self.show_hidden.setChecked(bool(settings.get("show_hidden", False)))
        self.show_hidden.toggled.connect(self._emit_changed)
        root_layout.addWidget(self.show_hidden)

        # ---- status + close ----
        self.status = QLabel("")
        self.status.setObjectName("scanStatus")
        self.status.setWordWrap(True)
        root_layout.addStretch(1)
        root_layout.addWidget(self.status)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(self._button("Close", self.accept))
        outer.addLayout(close_row)

        self._refresh_buttons()

    # ---- helpers ----
    def _button(self, text, slot):
        b = QPushButton(text)
        b.setObjectName("settingsButton")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _fill_list(self, widget, folders):
        for folder in folders:
            label = folder if Path(folder).is_dir() else f"{folder}   (missing on this machine)"
            widget.addItem(label)

    def _refresh_buttons(self):
        self.remove_btn.setEnabled(self.folder_list.count() > 0)
        self.scan_btn.setEnabled(self.folder_list.count() > 0)

    # ---- playback options ----
    def _on_volume(self, value):
        self.volume_label.setText(f"{value}%")
        self._emit_changed()

    def _emit_changed(self):
        self.settings["volume"] = self.volume.value()
        self.settings["slideshow_interval"] = self.interval.value()
        self.settings["start_fullscreen"] = self.fullscreen.isChecked()
        self.settings["resume_enabled"] = self.resume.isChecked()
        self.settings["show_hidden"] = self.show_hidden.isChecked()
        self.settingsChanged.emit(dict(self.settings))

    def _clear_resume(self):
        ResumeStore(self.root / "data" / "resume.json").clear_all()
        self.status.setText("Resume points cleared.")

    # ---- media folders ----
    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose a media folder")
        if folder and folder not in self.settings["scan_folders"]:
            self.settings["scan_folders"].append(folder)
            self.folder_list.addItem(folder)
            self._refresh_buttons()
            self.settingsChanged.emit(dict(self.settings))

    def _remove_folder(self):
        row = self.folder_list.currentRow()
        if row >= 0:
            self.folder_list.takeItem(row)
            del self.settings["scan_folders"][row]
            self._refresh_buttons()
            self.settingsChanged.emit(dict(self.settings))

    def _scan(self):
        self.status.setText("Scanning…")
        self.scan_btn.setEnabled(False)
        QApplication.processEvents()
        try:
            counts = scan_into_library(self.root / "data" / "library.json",
                                       self.settings["scan_folders"])
            total = sum(counts.values())
            detail = ", ".join(f"{k}: {v}" for k, v in counts.items() if v)
            self.status.setText(f"Found {total} files ({detail})." if total
                                else "No media files found in those folders.")
        except OSError as exc:
            self.status.setText(f"Scan failed: {exc}")
        finally:
            self._refresh_buttons()
