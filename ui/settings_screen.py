"""Settings screen: playback options, media folders, privacy toggle."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QListWidget, QSpinBox, QCheckBox,
                               QSlider, QFileDialog, QScrollArea,
                               QWidget, QFrame)

from core.scanner import scan_into_library
from core.resume import ResumeStore


class _ScanSignals(QObject):
    finished = Signal(dict)
    failed = Signal(str)


class _ScanTask(QRunnable):
    def __init__(self, library_path: Path, folders):
        super().__init__()
        self.library_path = library_path
        self.folders = list(folders)
        self.signals = _ScanSignals()

    def run(self):
        try:
            counts = scan_into_library(self.library_path, self.folders)
        except Exception as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(counts)


class SettingsDialog(QDialog):
    settingsChanged = Signal(dict)

    def __init__(self, root: Path, settings: dict, parent=None):
        super().__init__(parent)
        self.root = root
        self.settings = dict(settings)
        self.settings["scan_folders"] = list(settings["scan_folders"])
        self.settings["program_folders"] = list(settings.get("program_folders", []))
        self._scan_task = None
        self._closed = False
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
        self.add_folder_btn = self._button("Add folder…", self._add_folder)
        folder_buttons.addWidget(self.add_folder_btn)
        self.remove_btn = self._button("Remove", self._remove_folder)
        self.scan_btn = self._button("Scan now", self._scan)
        folder_buttons.addWidget(self.remove_btn)
        folder_buttons.addStretch(1)
        folder_buttons.addWidget(self.scan_btn)
        root_layout.addLayout(folder_buttons)

        # ---- applications (Quick Launch) ----
        section = QLabel("Applications (Quick Launch, F4)")
        section.setObjectName("settingsSection")
        root_layout.addWidget(section)

        self.discover_apps = QCheckBox("Discover apps installed on this system")
        self.discover_apps.setToolTip(
            "Reads Start Menu shortcuts on Windows, .desktop entries on Linux, "
            "and the Applications folders on macOS. Off by default.")
        self.discover_apps.setChecked(bool(settings.get("discover_apps", False)))
        self.discover_apps.toggled.connect(self._emit_changed)
        root_layout.addWidget(self.discover_apps)

        hint = QLabel("Program folders are scanned for launchable apps in the "
                      "background when Quick Launch opens.")
        hint.setObjectName("settingsHint")
        hint.setWordWrap(True)
        root_layout.addWidget(hint)

        self.program_list = QListWidget()
        self.program_list.setObjectName("folderList")
        self.program_list.setFixedHeight(96)
        self._fill_list(self.program_list, self.settings["program_folders"])
        root_layout.addWidget(self.program_list)

        program_buttons = QHBoxLayout()
        program_buttons.addWidget(
            self._button("Add program folder…", self._add_program_folder))
        self.remove_program_btn = self._button("Remove",
                                               self._remove_program_folder)
        program_buttons.addWidget(self.remove_program_btn)
        program_buttons.addStretch(1)
        root_layout.addLayout(program_buttons)

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
        scanning = self._scan_task is not None
        has_media = self.folder_list.count() > 0
        self.add_folder_btn.setEnabled(not scanning)
        self.remove_btn.setEnabled(has_media and not scanning)
        self.scan_btn.setEnabled(has_media and not scanning)
        self.remove_program_btn.setEnabled(self.program_list.count() > 0)

    def closeEvent(self, event):
        self._closed = True
        super().closeEvent(event)

    def done(self, result):
        self._closed = True
        super().done(result)

    # ---- playback options ----
    def _on_volume(self, value):
        self.volume_label.setText(f"{value}%")
        self._emit_changed()

    def _emit_changed(self):
        self.settings["volume"] = self.volume.value()
        self.settings["slideshow_interval"] = self.interval.value()
        self.settings["start_fullscreen"] = self.fullscreen.isChecked()
        self.settings["resume_enabled"] = self.resume.isChecked()
        self.settings["discover_apps"] = self.discover_apps.isChecked()
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

    # ---- program folders ----
    def _add_program_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose a program folder")
        if folder and folder not in self.settings["program_folders"]:
            self.settings["program_folders"].append(folder)
            self.program_list.addItem(folder)
            self._refresh_buttons()
            self.settingsChanged.emit(dict(self.settings))

    def _remove_program_folder(self):
        row = self.program_list.currentRow()
        if row >= 0:
            self.program_list.takeItem(row)
            del self.settings["program_folders"][row]
            self._refresh_buttons()
            self.settingsChanged.emit(dict(self.settings))

    def _scan(self):
        if self._scan_task is not None:
            return
        self.status.setText("Scanning media folders…")
        task = _ScanTask(self.root / "data" / "library.json",
                         self.settings["scan_folders"])
        task.signals.finished.connect(self._on_scan_done)
        task.signals.failed.connect(self._on_scan_failed)
        self._scan_task = task
        self._refresh_buttons()
        QThreadPool.globalInstance().start(task)

    def _on_scan_done(self, counts: dict):
        self._scan_task = None
        if self._closed:
            return
        total = sum(counts.values())
        detail = ", ".join(f"{k}: {v}" for k, v in counts.items() if v)
        self.status.setText(f"Found {total} files ({detail})." if total
                            else "No media files found in those folders.")
        self._refresh_buttons()

    def _on_scan_failed(self, message: str):
        self._scan_task = None
        if self._closed:
            return
        self.status.setText(f"Scan failed: {message}")
        self._refresh_buttons()
