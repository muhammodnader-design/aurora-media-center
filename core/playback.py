"""Playback controller.

Real playback through QtMultimedia for local video/audio, a timer-driven
picture slideshow, and local app launching. Items without a valid file
fall back to simulated playback so the shell always works out of the box.
"""
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices

from .library import resolve_file
from .resume import ResumeStore, key_for_file
from .apps import guess_kind, launch_app


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class PlaybackController(QObject):
    started = Signal(dict)                  # item dict
    positionChanged = Signal(float, float)  # position, duration (seconds / image count)
    playingChanged = Signal(bool)
    stopped = Signal()
    message = Signal(str)                   # status text for the footer
    videoActive = Signal(bool)              # show/hide the video stage
    imageChanged = Signal(str)              # slideshow: path of the current image

    def __init__(self, settings: dict, root: Path, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.root = root
        self.item = None
        self.kind = "video"
        self._mode = "idle"                 # idle | simulate | media | slideshow
        self._pos = 0.0
        self._dur = 180.0
        self._playing = False
        self._queue = []
        self._queue_index = -1
        self._resume = ResumeStore(root / "data" / "resume.json")
        self._resume_key = ""
        self._resume_target = 0.0
        self._last_saved = 0.0

        # real media
        self._player = QMediaPlayer(self)
        self._audio = None
        if QMediaDevices.audioOutputs():
            try:
                self._audio = QAudioOutput(self)
                self._player.setAudioOutput(self._audio)
                self._audio.setVolume(settings["volume"] / 100.0)
            except Exception:
                self._audio = None
        self._player.positionChanged.connect(self._media_position)
        self._player.durationChanged.connect(self._media_duration)
        self._player.playbackStateChanged.connect(self._media_state)
        self._player.mediaStatusChanged.connect(self._media_status)
        self._player.errorOccurred.connect(self._media_error)

        # simulation
        self._sim_timer = QTimer(self)
        self._sim_timer.setInterval(250)
        self._sim_timer.timeout.connect(self._sim_tick)

        # slideshow
        self._images = []
        self._image_index = 0
        self._slide_timer = QTimer(self)
        self._slide_timer.timeout.connect(self._slide_tick)

    # ================= configuration =================
    def set_video_output(self, widget):
        self._player.setVideoOutput(widget)

    def update_settings(self, settings: dict):
        self.settings = settings
        if self._audio is not None:
            self._audio.setVolume(settings["volume"] / 100.0)
        if self._mode == "slideshow" and self._playing:
            self._slide_timer.setInterval(settings["slideshow_interval"] * 1000)
            self._slide_timer.start()

    # ================= public API =================
    def play(self, item: dict, kind: str, category_items=None):
        self.stop()
        self.item = item
        self.kind = kind
        self._queue = list(category_items) if category_items else [item]
        try:
            self._queue_index = next(
                i for i, q in enumerate(self._queue)
                if q is item or (q.get("title") == item.get("title")
                                 and q.get("file") == item.get("file")))
        except StopIteration:
            self._queue = [item]
            self._queue_index = 0
        file = resolve_file(item, self.root)

        if kind == "app":
            self.item = None
            if file:
                ok, message = launch_app({
                    "title": item["title"],
                    "target": file,
                    "args": item.get("args") or [],
                    "kind": guess_kind(file),
                })
                self.message.emit(message if ok else f"Could not launch: {file}")
            else:
                self.message.emit(f"{item['title']}: no executable available on "
                                  "this platform — set \"file\" (or "
                                  "\"file_linux\" / \"file_windows\") in library.json.")
            return

        if kind == "pictures":
            images = [f for f in (resolve_file(it, self.root)
                                  for it in (category_items or [])) if f]
            if images:
                self._mode = "slideshow"
                self._images = images
                self._image_index = images.index(file) if file in images else 0
                self._pos = float(self._image_index + 1)
                self._dur = float(len(images))
                self._playing = True
                self._slide_timer.setInterval(self.settings["slideshow_interval"] * 1000)
                self._slide_timer.start()
                self.started.emit(item)
                self.playingChanged.emit(True)
                self.imageChanged.emit(self._images[self._image_index])
                self.positionChanged.emit(self._pos, self._dur)
                return
            self.message.emit("No image files found — simulated slideshow.")

        if kind in ("video", "audio") and file:
            self._mode = "media"
            self._pos = 0.0
            self._dur = max(1.0, float(item.get("duration", 180)))
            self._resume_key = key_for_file(file)
            self._resume_target = (self._resume.get(self._resume_key)
                                   if self.settings.get("resume_enabled", True)
                                   else 0.0)
            self._last_saved = 0.0
            self._player.setSource(QUrl.fromLocalFile(file))
            if kind == "video":
                self.videoActive.emit(True)
            self.started.emit(item)
            self._player.play()
            return

        if not file and (item.get("file") or item.get("file_windows")
                         or item.get("file_linux") or item.get("file_mac")):
            self.message.emit("File not found on this platform — simulating playback.")
        self._start_simulation(item)

    def toggle(self):
        if self.item is None:
            return
        if self._mode == "media":
            if self._player.playbackState() == QMediaPlayer.PlayingState:
                self._player.pause()
                self._remember_position()
            else:
                self._player.play()
        elif self._mode == "slideshow":
            self._playing = not self._playing
            if self._playing:
                self._slide_timer.start()
            else:
                self._slide_timer.stop()
            self.playingChanged.emit(self._playing)
        elif self._mode == "simulate":
            self._playing = not self._playing
            if self._playing:
                self._sim_timer.start()
            else:
                self._sim_timer.stop()
            self.playingChanged.emit(self._playing)

    def seek(self, delta_seconds: float):
        if self.item is None:
            return
        if self._mode == "media":
            target = self._player.position() + int(delta_seconds * 1000)
            self._player.setPosition(max(0, min(target, self._player.duration())))
        elif self._mode == "slideshow":
            step = 1 if delta_seconds > 0 else -1
            self._image_index = (self._image_index + step) % len(self._images)
            self._pos = float(self._image_index + 1)
            self.imageChanged.emit(self._images[self._image_index])
            self.positionChanged.emit(self._pos, self._dur)
        elif self._mode == "simulate":
            self._pos = min(max(0.0, self._pos + delta_seconds), self._dur)
            self.positionChanged.emit(self._pos, self._dur)

    def skip(self, delta: int):
        """Move to the previous/next item in the current category queue."""
        if self.item is None:
            return
        if self.kind == "pictures":
            self.seek(1 if delta > 0 else -1)
            return
        target = self._queue_index + (1 if delta > 0 else -1)
        if 0 <= target < len(self._queue):
            self.play(self._queue[target], self.kind, category_items=self._queue)
        else:
            self.message.emit("End of queue")

    def _advance_or_stop(self):
        """Auto-play the next queued item, or stop at the end."""
        if self.kind in ("audio", "video") and \
                self._queue_index + 1 < len(self._queue):
            self.skip(1)
        else:
            self.stop()

    def resume_position(self, item: dict) -> float:
        """Resume point for an item, in seconds (0 when none applies)."""
        if not self.settings.get("resume_enabled", True) or not item:
            return 0.0
        file = resolve_file(item, self.root)
        return self._resume.get(key_for_file(file)) if file else 0.0

    def _remember_position(self):
        if not self._resume_key or self.item is None:
            return
        if self._mode not in ("media", "simulate"):
            return
        if not self.settings.get("resume_enabled", True):
            return
        self._resume.update(self._resume_key, self._pos, self._dur)

    def stop(self):
        had_media = self.item is not None
        self._remember_position()
        # Drop the key before the player emits position 0 on stop, so that
        # reset can't erase the point we just saved.
        self._resume_key = ""
        self._resume_target = 0.0
        self._sim_timer.stop()
        self._slide_timer.stop()
        if self._mode == "media":
            self._player.stop()
            self._player.setSource(QUrl())
            self.videoActive.emit(False)
        self.item = None
        self._mode = "idle"
        self._playing = False
        self._images = []
        self._queue = []
        self._queue_index = -1
        if had_media:
            self.stopped.emit()

    @property
    def active(self) -> bool:
        return self.item is not None

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def playing(self) -> bool:
        return self._playing

    # ================= simulation =================
    def _start_simulation(self, item):
        self._mode = "simulate"
        self._pos = 0.0
        self._dur = max(1.0, float(item.get("duration", 180)))
        self._playing = True
        self._sim_timer.start()
        self.started.emit(item)
        self.playingChanged.emit(True)
        self.positionChanged.emit(self._pos, self._dur)

    def _sim_tick(self):
        self._pos += self._sim_timer.interval() / 1000.0
        if self._pos >= self._dur:
            self._advance_or_stop()
            return
        self.positionChanged.emit(self._pos, self._dur)

    # ================= slideshow =================
    def _slide_tick(self):
        self._image_index = (self._image_index + 1) % len(self._images)
        self._pos = float(self._image_index + 1)
        self.imageChanged.emit(self._images[self._image_index])
        self.positionChanged.emit(self._pos, self._dur)

    # ================= real media =================
    def _media_position(self, ms):
        if self._mode != "media":
            return
        self._pos = ms / 1000.0
        self.positionChanged.emit(self._pos, self._dur)
        if self._resume_key and abs(self._pos - self._last_saved) >= 5.0:
            self._last_saved = self._pos
            self._remember_position()

    def _media_duration(self, ms):
        if self._mode != "media" or ms <= 0:
            return
        self._dur = ms / 1000.0
        self.positionChanged.emit(self._pos, self._dur)

    def _media_state(self, state):
        if self._mode != "media":
            return
        self._playing = state == QMediaPlayer.PlayingState
        self.playingChanged.emit(self._playing)

    def _media_status(self, status):
        if self._mode != "media":
            return
        if status == QMediaPlayer.LoadedMedia and self._resume_target > 0:
            target, self._resume_target = self._resume_target, 0.0
            self._pos = target
            self._player.setPosition(int(target * 1000))
            self.positionChanged.emit(self._pos, self._dur)
            self.message.emit(f"Resuming from {fmt_time(target)}")
        elif status == QMediaPlayer.EndOfMedia:
            if self._resume_key:
                self._resume.update(self._resume_key, self._dur, self._dur)
            self._advance_or_stop()

    def _media_error(self, _error, error_string):
        if self._mode != "media":
            return
        self.message.emit(f"Playback error: {error_string}")
        item = self.item
        kind = self.kind
        queue = list(self._queue)
        queue_index = self._queue_index
        self.stop()
        if item is not None:
            self.item = item
            self.kind = kind
            self._queue = queue
            self._queue_index = queue_index
            self._start_simulation(item)
