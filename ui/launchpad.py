"""Quick Launch: a full-screen app launcher overlay.

Open with F4 from anywhere in Aurora. Type to filter, use the arrow keys to
browse, Enter to launch. Apps come from the library, from user-added program
folders, and — only when enabled in Settings — from installed applications.
"""
import sys
from pathlib import Path

from PySide6.QtCore import (Qt, QObject, QThreadPool, QRunnable, QTimer,
                            QFileInfo, QSize, Signal)
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QFileDialog, QFileIconProvider)

from core.apps import (discover_apps, launch_app, library_app_entries,
                       make_app, sort_apps)
from core.app_store import AppStore
from core.library import remove_library_item
from ui.app_grid import AppGrid

HINT = ("↑↓←→  Browse      Enter  Launch      Type  Filter      "
        "F2  Add app      F3  Sources      F5  Refresh      Esc  Close")
SEARCH_HINT = "🔍  Search apps…"


class _DiscoverSignals(QObject):
    finished = Signal(list)
    failed = Signal(str)


class _DiscoverTask(QRunnable):
    def __init__(self, discover_installed: bool, folders):
        super().__init__()
        self.discover_installed = discover_installed
        self.folders = list(folders)
        self.signals = _DiscoverSignals()

    def run(self):
        try:
            apps = discover_apps(self.discover_installed, self.folders)
        except Exception as exc:  # discovery must never break the overlay
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(apps)


class Launchpad(QWidget):
    closed = Signal()
    launched = Signal(str)      # footer message after a successful launch
    settingsRequested = Signal()
    fullscreenRequested = Signal()
    volumeRequested = Signal(int)
    libraryChanged = Signal()

    def __init__(self, root: Path, settings: dict, library_provider,
                 parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.settings = settings
        self.library_provider = library_provider
        self.store = AppStore(self.root / "data")
        self._query = ""
        self._all = []
        self._visible = []
        self._task = None
        self._task_sources = None
        self._icon_queue = []
        self._icon_timer = QTimer(self)
        self._icon_timer.setInterval(0)
        self._icon_timer.timeout.connect(self._icon_tick)
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(lambda: self.hint.setText(HINT))

        self.setObjectName("launchpad")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._build_ui()

    # ================= UI =================
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(46, 24, 46, 20)
        outer.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Quick Launch")
        title.setObjectName("launchTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.search = QLabel(SEARCH_HINT)
        self.search.setObjectName("launchSearch")
        self.search.setMinimumWidth(360)
        self.search.setFixedHeight(44)
        self.search.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.addWidget(self.search)
        close_btn = QPushButton("✕")
        close_btn.setObjectName("launchClose")
        close_btn.setFocusPolicy(Qt.NoFocus)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setToolTip("Close (Esc)")
        close_btn.clicked.connect(self.dismiss)
        header.addWidget(close_btn)
        outer.addLayout(header)

        self.grid = AppGrid()
        self.grid.activated.connect(self._launch)
        self.grid.selectionChanged.connect(self._on_selection)
        outer.addWidget(self.grid, 1)

        detail = QHBoxLayout()
        detail.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(2)
        self.sel_title = QLabel("")
        self.sel_title.setObjectName("launchItemTitle")
        self.sel_path = QLabel("")
        self.sel_path.setObjectName("launchItemPath")
        left.addWidget(self.sel_title)
        left.addWidget(self.sel_path)
        detail.addLayout(left, 1)

        self.launch_btn = self._button("Launch", self._launch_selected, "launchPrimary")
        self.pin_btn = self._button("Pin", self._toggle_pin)
        self.hide_btn = self._button("Hide", self._hide_selected)
        self.remove_btn = self._button("Remove", self._remove_selected, "launchDanger")
        self.add_btn = self._button("Add app…", self._add_app)
        self.sources_btn = self._button("Sources…", self.settingsRequested.emit)
        self.sources_btn.setToolTip("Configure app discovery and program folders (F3)")
        for btn in (self.launch_btn, self.pin_btn, self.hide_btn,
                    self.remove_btn, self.add_btn, self.sources_btn):
            detail.addWidget(btn)
        outer.addLayout(detail)

        self.hint = QLabel(HINT)
        self.hint.setObjectName("launchHint")
        outer.addWidget(self.hint)

    def _button(self, text, slot, name="launchButton"):
        btn = QPushButton(text)
        btn.setObjectName(name)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.clicked.connect(slot)
        return btn

    # ================= open / close =================
    def open(self):
        self._query = ""
        self._update_search_label()
        self._reload()
        self.setFocus(Qt.OtherFocusReason)
        self.show()
        self.raise_()
        if not self._sources_configured():
            self._flash(
                "Tip: Press F3 (Sources…) to add program folders or discover "
                "installed apps, or F2 to add an app.", 6000)
        else:
            self._maybe_discover()

    def dismiss(self):
        if not self.isVisible():
            return
        self.hide()
        self.closed.emit()

    def set_settings(self, settings: dict):
        self.settings = settings

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus(Qt.OtherFocusReason)

    # ================= data =================
    def _library_apps(self):
        try:
            library = self.library_provider() or {}
        except Exception:
            library = {}
        return library_app_entries(library, self.root)

    def _current_sources(self) -> dict:
        return {
            "installed": bool(self.settings.get("discover_apps", False)),
            "folders": [str(f) for f in self.settings.get("program_folders", [])],
        }

    def _sources_configured(self) -> bool:
        current = self._current_sources()
        return current["installed"] or bool(current["folders"])

    def _reload(self, keep_id=None):
        library_apps = self._library_apps()
        self.store.seed_pins(library_apps)
        self._all = self.store.merged(library_apps)
        show_hidden = bool(self.settings.get("show_hidden", False))
        self._visible = self.store.visible_apps(self._all, show_hidden)
        for app in self._all:
            icon = self.store.icon_path(app)
            app["icon_abs"] = str(icon) if icon.is_file() else ""
        self.grid.set_sections(
            self._sections(), keep_id,
            pinned_ids=self.store.pinned)
        self._queue_icons()

    def _sections(self):
        apps = sort_apps(self._visible)
        query = self._query.strip().casefold()
        if query:
            matches = [app for app in apps
                       if query in app.get("title", "").casefold()
                       or query in app.get("target", "").casefold()]
            return [("Results", matches)]

        pinned = self.store.pinned_apps(apps)
        pinned_ids = {app.get("id") for app in pinned}
        recent = [app for app in self.store.recent_apps(apps)
                  if app.get("id") not in pinned_ids]
        return [("Pinned", pinned), ("Recent", recent), ("All apps", apps)]

    def _update_search_label(self):
        if self._query:
            self.search.setText(f"🔍  {self._query}▌")
        else:
            self.search.setText(SEARCH_HINT)

    def _set_query(self, text: str):
        text = text[:60]
        if text == self._query:
            return
        self._query = text
        self._update_search_label()
        self.grid.set_sections(self._sections(), pinned_ids=self.store.pinned)
        self.hint.setText(HINT if not text else
                          "Type to filter      Backspace  Delete      Esc  Clear")

    # ================= selection =================
    def _on_selection(self, app):
        has = app is not None
        for btn in (self.launch_btn, self.pin_btn, self.hide_btn):
            btn.setEnabled(has)
        removable = has and app.get("source") in ("manual", "library")
        self.remove_btn.setEnabled(removable)
        if not has:
            self.sel_title.setText("No matching apps")
            self.sel_path.setText("Press F2 to add an application, or enable "
                                  "discovery in Settings (F3).")
            self.remove_btn.setToolTip("Remove the selected app (Delete)")
            return
        self.sel_title.setText(app.get("title", ""))
        args = " ".join(app.get("args") or [])
        path = app.get("target", "")
        self.sel_path.setText(f"{path}  {args}".strip())
        self.sel_path.setToolTip(path)
        self.pin_btn.setText("Unpin" if self.store.is_pinned(app.get("id")) else "Pin")
        hidden = self.store.is_hidden(app.get("id"))
        self.hide_btn.setText("Unhide" if hidden else "Hide")
        self.hide_btn.setToolTip(
            "Hidden apps stay out of this list unless Show private items is on." )
        self.remove_btn.setToolTip(
            "Remove from Apps / Quick Launch (Delete)" if removable
            else "Use Hide for auto-discovered apps, or remove its folder in Settings.")

    # ================= discovery =================
    def _maybe_discover(self):
        if self._task is not None or not self._sources_configured():
            return
        current = self._current_sources()
        if not self.store.discovered or self.store.sources != current:
            self._discover()

    def _discover(self, force=False):
        if self._task is not None:
            return
        sources = self._current_sources()
        if not (sources["installed"] or sources["folders"]):
            self._flash("Enable app discovery or add a program folder in "
                        "Settings (F3).", 5000)
            return
        if not force and self.store.discovered and self.store.sources == sources:
            self._flash("App list is already up to date. Press F5 to refresh.")
            return
        self._task_sources = sources
        self._flash("Looking for apps…", 0)
        task = _DiscoverTask(sources["installed"], sources["folders"])
        task.signals.finished.connect(self._on_discovered)
        task.signals.failed.connect(self._on_discovery_failed)
        self._task = task
        QThreadPool.globalInstance().start(task)

    def _on_discovered(self, apps):
        sources = self._task_sources or self._current_sources()
        self._task = None
        self.store.set_discovered(apps, sources)
        keep = self.grid.focus_id()
        self._reload(keep)
        if apps:
            self._flash(f"Found {len(apps)} apps.")
        else:
            self._flash("No apps found in the selected sources.")

    def _on_discovery_failed(self, message):
        self._task = None
        self._flash(f"App discovery failed: {message}", 6000)

    # ================= icons =================
    def _queue_icons(self):
        seen = set()
        queue = []
        for app in self._visible:
            aid = app.get("id")
            if not aid or aid in seen or self.store.has_icon(app):
                continue
            seen.add(aid)
            queue.append(app)
        self._icon_queue = queue
        if queue and not self._icon_timer.isActive():
            self._icon_timer.start()

    def _icon_tick(self):
        if not self._icon_queue:
            self._icon_timer.stop()
            return
        app = self._icon_queue.pop(0)
        if self._extract_icon(app):
            app["icon_abs"] = str(self.store.icon_path(app))
            self.grid.refresh()
        if not self._icon_queue:
            self._icon_timer.stop()
            self.store.save_state()
            self.store.save_cache()

    def _extract_icon(self, app) -> bool:
        try:
            icon = None
            name = str(app.get("icon_name") or "")
            if name:
                path = Path(name)
                icon = QIcon(str(path)) if path.is_absolute() else QIcon.fromTheme(name)
            if icon is None or icon.isNull():
                icon = QFileIconProvider().icon(QFileInfo(app.get("target", "")))
            if icon is None or icon.isNull():
                return False
            pixmap = icon.pixmap(QSize(128, 128))
            if pixmap.isNull():
                return False
            target = self.store.icon_dir / f"{app['id']}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            if not pixmap.save(str(target), "PNG"):
                return False
            app["icon"] = f"app_icons/{app['id']}.png"
            return True
        except (OSError, RuntimeError):
            return False

    # ================= actions =================
    def _selected(self):
        return self.grid.current_app()

    def _launch_selected(self):
        app = self._selected()
        if app is not None:
            self._launch(app)

    def _launch(self, app):
        ok, message = launch_app(app)
        if not ok:
            self._flash(message, 5000)
            return
        self.store.record_launch(app.get("id"))
        self.sel_title.setText(app.get("title", ""))
        self.dismiss()
        self.launched.emit(message)

    def _toggle_pin(self):
        app = self._selected()
        if app is None:
            return
        pinned = self.store.toggle_pin(app.get("id"))
        self._reload(app.get("id"))
        self._flash(f"{'Pinned' if pinned else 'Unpinned'} {app.get('title')}.")

    def _hide_selected(self):
        app = self._selected()
        if app is None:
            return
        aid = app.get("id")
        if self.store.is_hidden(aid) and self.settings.get("show_hidden", False):
            self.store.unhide(aid)
            self._flash(f"Showing {app.get('title')} again.")
        else:
            self.store.hide(aid)
            self._flash("Hidden. Turn on Show private items in Settings to "
                        "see it again.", 5000)
        self._reload()

    def _remove_selected(self):
        app = self._selected()
        if app is None:
            return
        aid = app.get("id")
        title = app.get("title", "app")
        source = app.get("source")
        if source == "manual":
            if self.store.remove_manual(aid):
                self._reload()
                self._flash(f"Removed {title}.")
        elif source == "library":
            lib_path = self.root / "data" / "library.json"
            if remove_library_item(lib_path, "apps", app, self.root):
                self.store.forget_id(aid)
                self.libraryChanged.emit()
                self._reload()
                self._flash(f"Removed {title} from Apps.")
        else:
            self._flash("Use Hide for auto-discovered apps, or remove its "
                        "folder in Settings (F3).", 4500)

    def _add_app(self):
        if sys.platform == "win32":
            filters = "Applications (*.exe *.lnk *.bat *.cmd);;All files (*)"
        elif sys.platform == "darwin":
            filters = "Applications (*.app);;All files (*)"
        else:
            filters = "Applications (*.desktop *.AppImage);;All files (*)"
        path, _ = QFileDialog.getOpenFileName(self, "Add an app", "", filters)
        if not path:
            return
        title = Path(path).stem or Path(path).name
        app = make_app(title, path, source="manual")
        self.store.add_manual(app)
        if app["id"] not in self.store.pinned:
            self.store.pinned.append(app["id"])
        self.store.save_state()
        self._query = ""
        self._update_search_label()
        self._reload(app["id"])
        self._flash(f"Added {app['title']}.")

    # ================= keyboard =================
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key_Escape:
            if self._query:
                self._set_query("")
            else:
                self.dismiss()
            return
        if key == Qt.Key_F4:
            self.dismiss()
            return
        if key == Qt.Key_Up:
            self.grid.move_focus(0, -1)
            return
        if key == Qt.Key_Down:
            self.grid.move_focus(0, 1)
            return
        if key == Qt.Key_Left:
            self.grid.move_focus(-1, 0)
            return
        if key == Qt.Key_Right:
            self.grid.move_focus(1, 0)
            return
        if key == Qt.Key_Home:
            self.grid.set_focus(0)
            return
        if key == Qt.Key_End:
            self.grid.set_focus(max(0, self.grid.focus_count() - 1))
            return
        if key == Qt.Key_PageUp:
            self.grid.move_page(-1)
            return
        if key == Qt.Key_PageDown:
            self.grid.move_page(1)
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.grid.activate_focused()
            return
        if key == Qt.Key_Backspace:
            self._set_query(self._query[:-1])
            return
        if key == Qt.Key_Delete:
            self._remove_selected()
            return
        if key == Qt.Key_F2:
            self._add_app()
            return
        if key == Qt.Key_F3:
            self.settingsRequested.emit()
            return
        if key == Qt.Key_F5:
            self._discover(force=True)
            return
        if key == Qt.Key_F11:
            self.fullscreenRequested.emit()
            return
        if key == Qt.Key_VolumeUp:
            self.volumeRequested.emit(5)
            return
        if key == Qt.Key_VolumeDown:
            self.volumeRequested.emit(-5)
            return
        if not self._query and key in (Qt.Key_Plus, Qt.Key_Equal):
            self.volumeRequested.emit(5)
            return
        if not self._query and key == Qt.Key_Minus:
            self.volumeRequested.emit(-5)
            return
        if mods & Qt.ControlModifier and key == Qt.Key_P:
            self._toggle_pin()
            return
        if mods & Qt.ControlModifier and key == Qt.Key_H:
            self._hide_selected()
            return
        text = event.text()
        if text and text.isprintable():
            self._set_query(self._query + text)
            return
        super().keyPressEvent(event)

    # ================= misc =================
    def _flash(self, message: str, ms: int = 3000):
        self.hint.setText(message)
        if ms > 0:
            self._hint_timer.start(ms)

    def wheelEvent(self, event):
        # The grid normally receives wheel events; this catches the margins.
        self.grid.wheelEvent(event)
