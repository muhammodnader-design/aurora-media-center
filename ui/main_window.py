"""Aurora main window: layout, navigation, hot reload, quit confirmation."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QUrl
from PySide6.QtGui import QShortcut, QKeySequence, QPixmap, QDesktopServices
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QPushButton, QDialog)

from core.library import (load_library, kind_for, prune_unavailable_scanned,
                          hide_private_items)
from core.theme import load_stylesheet
from core.settings import save_settings
from core.hotreload import FileWatcher
from core.playback import PlaybackController
from ui.background import GlowBackground
from ui.category_menu import CategoryMenu
from ui.tile_row import TileRow
from ui.now_playing import NowPlayingBar, fmt_time
from ui.quit_dialog import QuitDialog
from ui.volume_osd import VolumeOSD
from ui.settings_screen import SettingsDialog
from ui.art import art_pixmap

FOOTER_HINT = ("↑↓  Category      ←→  Browse      Enter / Space  Play · Pause      "
               "⏮ / ⏭  Skip      + / −  Volume      Esc  Close      F2  Config      "
               "F3  Settings      F11  Fullscreen")


class MainWindow(QMainWindow):
    def __init__(self, root: Path, settings: dict):
        super().__init__()
        self.root = root
        self.settings = settings
        self.setWindowTitle("Aurora")
        self.setObjectName("auroraRoot")
        self._force_quit = False

        # ---- central widget = animated background ----
        central = GlowBackground()
        self.setCentralWidget(central)
        self.central = central

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(36, 22, 36, 14)
        root_layout.setSpacing(10)

        # top bar
        top = QHBoxLayout()
        brand = QLabel("AURORA")
        brand.setObjectName("brand")
        self.clock = QLabel("")
        self.clock.setObjectName("clock")
        self.gear = QPushButton("⚙")
        self.gear.setObjectName("gearButton")
        self.gear.setFocusPolicy(Qt.NoFocus)
        self.gear.setCursor(Qt.PointingHandCursor)
        self.gear.setToolTip("Settings (F3)")
        self.gear.clicked.connect(self._open_settings)
        top.addWidget(brand)
        top.addStretch(1)
        top.addWidget(self.gear)
        top.addWidget(self.clock)
        root_layout.addLayout(top)

        # middle: category menu | tiles + detail
        middle = QHBoxLayout()
        middle.setSpacing(24)
        self.menu = CategoryMenu()
        self.menu.setFixedWidth(330)
        self.menu.categoryClicked.connect(self._on_category_clicked)
        middle.addWidget(self.menu, 0)

        right = QVBoxLayout()
        right.setSpacing(8)
        self.tiles = TileRow()
        self.tiles.setFixedHeight(360)
        self.tiles.tileClicked.connect(self._on_tile_clicked)
        self.tiles.focusChanged.connect(lambda _i: self._update_detail())
        right.addWidget(self.tiles)

        self.detail_title = QLabel("")
        self.detail_title.setObjectName("detailTitle")
        self.detail_meta = QLabel("")
        self.detail_meta.setObjectName("detailMeta")
        self.detail_desc = QLabel("")
        self.detail_desc.setObjectName("detailDesc")
        self.detail_desc.setWordWrap(True)
        self.detail_desc.setMaximumWidth(760)
        self.play_button = QPushButton("▶  Play")
        self.play_button.setObjectName("playButton")
        self.play_button.setFocusPolicy(Qt.NoFocus)
        self.play_button.setCursor(Qt.PointingHandCursor)
        self.play_button.clicked.connect(self._play_focused)
        right.addWidget(self.detail_title)
        right.addWidget(self.detail_meta)
        right.addWidget(self.detail_desc)
        right.addWidget(self.play_button, 0, Qt.AlignLeft)
        right.addStretch(1)
        middle.addLayout(right, 1)
        root_layout.addLayout(middle, 1)

        # footer hint
        self.footer = QLabel(FOOTER_HINT)
        self.footer.setObjectName("footerHint")
        self.footer.setAlignment(Qt.AlignCenter)
        root_layout.addWidget(self.footer)

        # now playing overlay (absolute-positioned child, slides up)
        self.nowbar = NowPlayingBar(central)
        self.nowbar.hide()
        self.nowbar.seekRequested.connect(lambda d: self.controller.seek(d))
        self.nowbar.skipRequested.connect(lambda d: self.controller.skip(d))
        self.nowbar.toggleRequested.connect(self.controller_toggle)
        self.nowbar.closeRequested.connect(self.controller_stop)
        self._bar_anim = QPropertyAnimation(self.nowbar, b"pos", self)
        self._bar_anim.setDuration(320)
        self._bar_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._bar_anim.finished.connect(self._hide_bar)
        self._bar_shown = False
        self.volume_osd = VolumeOSD(central)

        # playback
        self.controller = PlaybackController(settings, root, self)
        self.controller.started.connect(self._on_started)
        self.controller.positionChanged.connect(self._on_position)
        self.controller.playingChanged.connect(self._on_playing_changed)
        self.controller.stopped.connect(self._on_stopped)
        self.controller.message.connect(self.show_footer_message)
        self.controller.videoActive.connect(self._set_video_visible)
        self.controller.imageChanged.connect(self._show_image)
        self._last_pos = (0.0, 0.0)
        self._last_playing = False

        # full-window media stages (under the now-playing overlay)
        self.video_stage = QVideoWidget(central)
        self.video_stage.setFocusPolicy(Qt.NoFocus)
        self.video_stage.hide()
        self.controller.set_video_output(self.video_stage)
        self.slide_stage = QLabel(central)
        self.slide_stage.setObjectName("slideshowStage")
        self.slide_stage.setAlignment(Qt.AlignCenter)
        self.slide_stage.setFocusPolicy(Qt.NoFocus)
        self.slide_stage.hide()
        self._slide_path = ""

        # clock
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

        # footer message restore
        self._footer_timer = QTimer(self)
        self._footer_timer.setSingleShot(True)
        self._footer_timer.timeout.connect(lambda: self.footer.setText(FOOTER_HINT))

        # data + hot reload
        self.library = {"categories": []}
        self._hidden_notified = False
        self._load_library()
        self._watcher = FileWatcher(
            [root / "theme" / "theme.qss", root / "data" / "library.json"], self)
        self._watcher.changed.connect(self._on_file_changed)

        # Alt+F4 must reach closeEvent even frameless/fullscreen
        QShortcut(QKeySequence("Alt+F4"), self).activated.connect(self.close)

    # ================= library / categories =================
    def _load_library(self):
        self.library = load_library(self.root / "data" / "library.json")
        skipped = prune_unavailable_scanned(self.library, self.root)
        if skipped and not self._hidden_notified:
            self._hidden_notified = True
            self.show_footer_message(
                f"{skipped} library items skipped — their files aren't on this "
                "machine. Press F3 to scan local folders.", 8000)
        hide_private_items(self.library, self.settings.get("show_hidden", False))
        cats = self.library["categories"]
        keep_id = self._current_category_id()
        keep = next((i for i, c in enumerate(cats) if c["id"] == keep_id), 0)
        self.menu.set_categories(cats, keep)
        self._show_category(self.menu.selected)

    def _current_category_id(self):
        cats = self.library.get("categories", [])
        i = self.menu.selected if hasattr(self, "menu") else 0
        return cats[i]["id"] if 0 <= i < len(cats) else None

    def _current_category(self):
        cats = self.library["categories"]
        i = self.menu.selected
        return cats[i] if 0 <= i < len(cats) else None

    def _focused_item(self):
        cat = self._current_category()
        if not cat:
            return None
        i = self.tiles.focus_index
        return cat["items"][i] if 0 <= i < len(cat["items"]) else None

    def _show_category(self, index):
        cats = self.library["categories"]
        if not (0 <= index < len(cats)):
            self.tiles.set_items([])
            self._update_detail()
            return
        self.tiles.set_items(cats[index]["items"])
        self._update_detail()

    def _on_category_clicked(self, index):
        self.menu.select(index)
        self._show_category(index)

    def _on_tile_clicked(self, index):
        if index == self.tiles.focus_index:
            self._play_focused()
        else:
            self.tiles.set_focus(index)

    def _update_detail(self):
        item = self._focused_item()
        cat = self._current_category()
        if item is None:
            self.detail_title.setText(cat["label"] if cat else "Aurora")
            self.detail_meta.setText("")
            self.detail_desc.setText("This category is empty. Edit data/library.json "
                                     "or add folders in Settings.")
            self.play_button.hide()
            return
        self.detail_title.setText(item["title"])
        self.detail_meta.setText(item["meta"])
        self.detail_desc.setText(item["description"])
        kind = kind_for(item, cat["id"])
        resume = self.controller.resume_position(item) if kind in ("video", "audio") else 0.0
        if kind == "app":
            self.play_button.setText("🎮  Play" if cat["id"] == "games"
                                     else "🚀  Launch")
        elif resume >= 1:
            self.play_button.setText(f"▶  Resume {fmt_time(resume)}")
        else:
            self.play_button.setText("▶  Play")
        self.play_button.show()

    # ================= playback wiring =================
    def _play_focused(self):
        item = self._focused_item()
        cat = self._current_category()
        if item is None or cat is None:
            return
        self.controller.play(item, kind_for(item, cat["id"]),
                             category_items=cat["items"])

    def controller_toggle(self):
        if self.controller.active:
            self.controller.toggle()
        else:
            self._play_focused()

    def controller_stop(self):
        self.controller.stop()

    def _on_started(self, item):
        self.nowbar.set_media(item["title"], art_pixmap(
            item["hue"], item["icon"], 96, 96, 12, icon_path=item.get("art", "")))
        self.nowbar.count_mode = (self.controller.kind == "pictures"
                                  and self.controller.mode == "slideshow")
        self._last_pos = (0.0, max(1.0, item.get("duration", 180)))
        self._last_playing = True
        self.nowbar.set_state(True, *self._last_pos)
        self._slide_bar(True)

    def _on_position(self, pos, dur):
        self._last_pos = (pos, dur)
        self.nowbar.set_state(self._last_playing, pos, dur)

    def _on_playing_changed(self, playing):
        self._last_playing = playing
        self.nowbar.set_state(playing, *self._last_pos)

    def _on_stopped(self):
        self.video_stage.hide()
        self.slide_stage.hide()
        self._slide_path = ""
        self._slide_bar(False)
        self._update_detail()

    # ================= media stages =================
    def _set_video_visible(self, visible):
        if visible:
            self.slide_stage.hide()
            self.video_stage.setGeometry(self.central.rect())
            self.video_stage.show()
            self.video_stage.raise_()
            self.nowbar.raise_()
        else:
            self.video_stage.hide()

    def _show_image(self, path):
        self._slide_path = path
        pm = QPixmap(path)
        if pm.isNull():
            return
        self.video_stage.hide()
        self.slide_stage.setGeometry(self.central.rect())
        self.slide_stage.setPixmap(pm.scaled(self.central.size(),
                                             Qt.KeepAspectRatio,
                                             Qt.SmoothTransformation))
        self.slide_stage.show()
        self.slide_stage.raise_()
        self.nowbar.raise_()

    # ================= now playing slide =================
    def _bar_geometry(self, shown):
        margin = 36
        w = self.central.width() - 2 * margin
        self.nowbar.setFixedWidth(max(400, w))
        y_shown = self.central.height() - self.nowbar.height() - 44
        y_hidden = self.central.height() + 4
        return QPoint(margin, y_shown if shown else y_hidden)

    def _slide_bar(self, show):
        if show == self._bar_shown and (self.nowbar.isVisible() or not show):
            if show:
                return
        self._bar_shown = show
        self._bar_anim.stop()
        if show:
            self.nowbar.move(self._bar_geometry(False))
            self.nowbar.show()
            self.nowbar.raise_()
        self._bar_anim.setStartValue(self.nowbar.pos())
        self._bar_anim.setEndValue(self._bar_geometry(show))
        self._bar_anim.start()

    def _hide_bar(self):
        if not self._bar_shown:
            self.nowbar.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._bar_shown:
            self._bar_anim.stop()
            self.nowbar.move(self._bar_geometry(True))
        else:
            self.nowbar.setFixedWidth(max(400, self.central.width() - 72))
        if self.video_stage.isVisible():
            self.video_stage.setGeometry(self.central.rect())
        if self.slide_stage.isVisible():
            self.slide_stage.setGeometry(self.central.rect())
            if self._slide_path:
                self._show_image(self._slide_path)
        if self.volume_osd.isVisible():
            self.volume_osd.reposition()

    # ================= hot reload =================
    def _on_file_changed(self, path):
        p = Path(path)
        if p.name == "theme.qss":
            app = self.window()
            from PySide6.QtWidgets import QApplication
            QApplication.instance().setStyleSheet(load_stylesheet(p))
            self.show_footer_message("Theme reloaded")
        elif p.name == "library.json":
            self._load_library()
            self.show_footer_message("Library reloaded")

    # ================= misc =================
    def _tick_clock(self):
        from PySide6.QtCore import QTime
        self.clock.setText(QTime.currentTime().toString("HH:mm:ss"))

    def show_footer_message(self, text, ms=3000):
        self.footer.setText(text)
        self._footer_timer.start(ms)

    def _open_config_folder(self):
        # opens Explorer / Nautilus / Dolphin etc. — fully local
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root)))

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _change_volume(self, delta):
        vol = max(0, min(100, int(self.settings.get("volume", 80)) + delta))
        if vol == self.settings.get("volume"):
            self.volume_osd.show_level(vol)
            return
        self.settings["volume"] = vol
        save_settings(self.root / "data" / "settings.json", self.settings)
        self.controller.update_settings(self.settings)
        self.volume_osd.show_level(vol)

    def _open_settings(self):
        dialog = SettingsDialog(self.root, self.settings, self)
        dialog.settingsChanged.connect(self._apply_settings)
        dialog.exec()

    def _apply_settings(self, settings):
        old_show_hidden = self.settings.get("show_hidden", False)
        self.settings = settings
        save_settings(self.root / "data" / "settings.json", settings)
        self.controller.update_settings(settings)
        if settings.get("show_hidden", False) != old_show_hidden:
            self._load_library()

    # ================= keyboard =================
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Up:
            self._on_category_clicked(self.menu.selected - 1)
        elif key == Qt.Key_Down:
            self._on_category_clicked(self.menu.selected + 1)
        elif key == Qt.Key_Left:
            self.tiles.move_focus(-1)
        elif key == Qt.Key_Right:
            self.tiles.move_focus(1)
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.controller_toggle()
        elif key in (Qt.Key_MediaPlay, Qt.Key_MediaPause, Qt.Key_MediaTogglePlayPause):
            self.controller_toggle()
        elif key == Qt.Key_MediaNext:
            self.controller.skip(1)
        elif key == Qt.Key_MediaPrevious:
            self.controller.skip(-1)
        elif key in (Qt.Key_VolumeUp, Qt.Key_Plus, Qt.Key_Equal):
            self._change_volume(5)
        elif key in (Qt.Key_VolumeDown, Qt.Key_Minus):
            self._change_volume(-5)
        elif key == Qt.Key_Escape:
            if self.controller.active:
                self.controller_stop()
        elif key == Qt.Key_F2:
            self._open_config_folder()
        elif key == Qt.Key_F3:
            self._open_settings()
        elif key == Qt.Key_F11:
            self._toggle_fullscreen()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self._change_volume(5 if delta > 0 else -5)
            event.accept()
        else:
            super().wheelEvent(event)

    # ================= quit confirmation =================
    def closeEvent(self, event):
        if self._force_quit:
            self.controller.stop()
            event.accept()
            return
        dialog = QuitDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.controller.stop()
            event.accept()
        else:
            event.ignore()

    def force_quit(self):
        """Used by --smoke-test to exit without the dialog."""
        self._force_quit = True
        self.close()
