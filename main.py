"""Aurora — a fully local, offline media-center shell (10-foot UI)."""
import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from core.theme import load_stylesheet
from core.settings import ensure_settings, load_settings
from core.library import ensure_library
from ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Aurora media center")
    parser.add_argument("--smoke-test", action="store_true",
                        help="start, run for a few seconds, then quit (no dialog)")
    parser.add_argument("--windowed", action="store_true",
                        help="start in a window instead of fullscreen")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Aurora")
    app.setOrganizationName("Aurora")
    app.setStyleSheet(load_stylesheet(ROOT / "theme" / "theme.qss"))

    ensure_library(ROOT / "data" / "library.json")
    ensure_settings(ROOT / "data" / "settings.json")
    settings = load_settings(ROOT / "data" / "settings.json")
    win = MainWindow(ROOT, settings)
    if args.windowed or not settings["start_fullscreen"]:
        win.resize(1440, 860)
        win.show()
    else:
        win.showFullScreen()

    if args.smoke_test:
        QTimer.singleShot(3000, win.force_quit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
