"""QFileSystemWatcher-based hot reload with debounce.

Many editors save by replacing the file (rename), which drops the watch;
we also watch the parent directory and re-add the file when it reappears.
"""
from pathlib import Path

from PySide6.QtCore import QObject, QFileSystemWatcher, QTimer, Signal


class FileWatcher(QObject):
    changed = Signal(str)  # absolute path of the changed file

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self._paths = [str(Path(p).resolve()) for p in paths]
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        self._timers = {}
        for p in self._paths:
            self._add(p)
            parent_dir = str(Path(p).parent)
            if parent_dir not in self._watcher.directories():
                self._watcher.addPath(parent_dir)

    def _add(self, path: str):
        if Path(path).exists() and path not in self._watcher.files():
            self._watcher.addPath(path)

    def _schedule(self, path: str):
        timer = self._timers.get(path)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(150)
            timer.timeout.connect(lambda p=path: self.changed.emit(p))
            self._timers[path] = timer
        timer.start()

    def _on_file_changed(self, path: str):
        self._add(path)  # re-arm after replace-by-rename saves
        self._schedule(path)

    def _on_dir_changed(self, _dir: str):
        for p in self._paths:
            if Path(p).parent == Path(_dir):
                existed = p in self._watcher.files()
                self._add(p)
                if not existed and Path(p).exists():
                    self._schedule(p)
