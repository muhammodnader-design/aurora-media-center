"""Automated regression tests for Aurora core modules and 10-foot UI."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.app_store import AppStore
from core.apps import _desktop_exec_tokens, make_app, scan_program_folder
from core.library import (hide_private_items, load_library,
                          prune_unavailable_scanned, remove_library_item,
                          save_library)
from core.playback import PlaybackController
from core.scanner import scan_into_library
from core.settings import DEFAULTS, load_settings
from ui.main_window import MainWindow


def _qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["aurora-test"])
    return app


class LibraryAndScannerTests(unittest.TestCase):
    def test_load_library_preserves_custom_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "library.json"
            raw = {
                "categories": [{
                    "id": "movies",
                    "label": "Movies",
                    "icon": "🎬",
                    "custom_cat": "keep-me",
                    "items": [{
                        "title": "Sample",
                        "file": "sample.mp4",
                        "year": 2025,
                        "tags": ["sci-fi"],
                    }],
                }]
            }
            p.write_text(json.dumps(raw), encoding="utf-8")
            lib = load_library(p, Path(tmp))
            save_library(p, lib)
            reloaded = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["categories"][0]["custom_cat"], "keep-me")
            item = reloaded["categories"][0]["items"][0]
            self.assertEqual(item["year"], 2025)
            self.assertEqual(item["tags"], ["sci-fi"])

    def test_scanner_ts_and_tv_word_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            (media / "slideshows").mkdir(parents=True)
            (media / "private").mkdir(parents=True)
            (media / "TV Shows" / "Season 1").mkdir(parents=True)

            # TypeScript file must not be classified as video
            (media / "slideshows" / "app.ts").write_text(
                "export const x: number = 1;\n", encoding="utf-8")
            # Real MPEG-TS packet (sync byte 0x47 at 0 and 188)
            packet = b"\x47" + b"\x00" * 187 + b"\x47" + b"\x00" * 10
            (media / "TV Shows" / "Season 1" / "episode.ts").write_bytes(packet)
            # Substring traps ("slideshows" contains "shows", "private" contains "tv"? no, "activity" does)
            (media / "activity").mkdir(parents=True)
            (media / "slideshows" / "clip1.mp4").write_bytes(b"00")
            (media / "activity" / "clip2.mp4").write_bytes(b"00")

            lib_path = base / "library.json"
            lib_path.write_text(json.dumps({"categories": []}), encoding="utf-8")
            counts = scan_into_library(lib_path, [str(media)])

            self.assertEqual(counts["tv"], 1)
            self.assertEqual(counts["movies"], 2)
            lib = load_library(lib_path, base)
            by_id = {c["id"]: c for c in lib["categories"]}
            self.assertEqual([i["title"] for i in by_id["tv"]["items"]], ["episode"])
            movie_titles = {i["title"] for i in by_id["movies"]["items"]}
            self.assertEqual(movie_titles, {"clip1", "clip2"})

    def test_privacy_and_prune(self):
        lib = {
            "categories": [{
                "id": "movies",
                "items": [
                    {"title": "Public", "file": "missing.mp4", "scanned": False, "hidden": False},
                    {"title": "GoneScan", "file": "missing.mp4", "scanned": True, "hidden": False},
                    {"title": "Secret", "file": "missing.mp4", "scanned": False, "hidden": True},
                ],
            }]
        }
        removed = prune_unavailable_scanned(lib, ROOT)
        self.assertEqual(removed, 1)
        hide_private_items(lib, show_hidden=False)
        self.assertEqual([i["title"] for i in lib["categories"][0]["items"]], ["Public"])


class AppsAndStoreTests(unittest.TestCase):
    def test_desktop_exec_tokens_strips_field_codes(self):
        tokens = _desktop_exec_tokens('/usr/bin/app --flag %U --pct %% "%f"')
        self.assertEqual(tokens, ["/usr/bin/app", "--flag", "--pct", "%"])

    def test_program_folder_picks_main_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            prog = Path(tmp) / "MyTool"
            prog.mkdir()
            (prog / "uninstall.exe").write_bytes(b"0" * 5000)
            (prog / "MyTool.exe").write_bytes(b"0" * 2000)
            (prog / "readme.txt").write_text("hi", encoding="utf-8")

            apps = scan_program_folder(Path(tmp))
            self.assertEqual(len(apps), 1)
            self.assertEqual(apps[0]["title"], "MyTool")
            self.assertTrue(apps[0]["target"].endswith("MyTool.exe"))

    def test_app_store_hide_scrubs_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AppStore(Path(tmp))
            a1 = make_app("Alpha", "/bin/alpha", source="manual")
            a2 = make_app("Beta", "/bin/beta", source="manual")
            store.add_manual(a1)
            store.add_manual(a2)
            store.toggle_pin(a1["id"])
            store.record_launch(a1["id"])
            store.record_launch(a2["id"])
            self.assertIn(a1["id"], store.recent)

            store.hide(a1["id"])
            self.assertNotIn(a1["id"], store.pinned)
            self.assertNotIn(a1["id"], store.recent)
            store.record_launch(a1["id"])
            self.assertNotIn(a1["id"], store.recent)
            vis = store.visible_apps(store.merged(), show_hidden=False)
            self.assertEqual([a["title"] for a in vis], ["Beta"])


class PlaybackAndUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _qt_app()

    def test_media_error_preserves_queue(self):
        settings = dict(DEFAULTS)
        ctrl = PlaybackController(settings, ROOT)
        items = [
            {"title": "One", "file": "does_not_exist_1.mp4", "duration": 10},
            {"title": "Two", "file": "does_not_exist_2.mp4", "duration": 10},
        ]
        # Force media mode directly to test _media_error recovery
        ctrl._queue = list(items)
        ctrl._queue_index = 0
        ctrl.kind = "video"
        ctrl.item = items[0]
        ctrl._mode = "media"
        ctrl._media_error(None, "decode error")

        self.assertEqual(ctrl.mode, "simulate")
        self.assertEqual(len(ctrl._queue), 2)
        self.assertEqual(ctrl._queue_index, 0)
        ctrl.skip(1)
        self.assertEqual(ctrl.item["title"], "Two")
        ctrl.stop()

    def test_mainwindow_apps_and_launchpad_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            (tmp_root / "data").mkdir()
            (tmp_root / "theme").mkdir()
            (tmp_root / "data" / "library.json").write_text(
                (ROOT / "data" / "library.example.json").read_text(encoding="utf-8"),
                encoding="utf-8")
            (tmp_root / "theme" / "theme.qss").write_text(
                (ROOT / "theme" / "theme.qss").read_text(encoding="utf-8"),
                encoding="utf-8")

            settings = load_settings(ROOT / "data" / "settings.example.json")
            settings["start_fullscreen"] = False
            win = MainWindow(tmp_root, settings)
            win.resize(1280, 760)
            win.show()
            self.app.processEvents()

            # Navigate to the "apps" category
            apps_idx = next(i for i, c in enumerate(win.library["categories"])
                            if c["id"] == "apps")
            win._on_category_clicked(apps_idx)
            self.app.processEvents()
            self.assertTrue(win.browse_apps_btn.isVisible())

            # Open Quick Launch via F4
            QTest.keyClick(win, Qt.Key_F4)
            self.app.processEvents()
            self.assertIsNotNone(win.launchpad)
            self.assertTrue(win.launchpad.isVisible())

            # Filter by typing and clear with Esc
            QTest.keyClicks(win.launchpad, "calc")
            self.app.processEvents()
            self.assertEqual(win.launchpad._query, "calc")
            self.assertEqual(win.launchpad.grid.current_app()["title"], "Calculator")

            QTest.keyClick(win.launchpad, Qt.Key_Escape)
            self.app.processEvents()
            self.assertEqual(win.launchpad._query, "")

            # Close Quick Launch with Esc
            QTest.keyClick(win.launchpad, Qt.Key_Escape)
            self.app.processEvents()
            self.assertFalse(win.launchpad.isVisible())

            # Remove the first app from the Apps section via Delete key
            before_titles = [it["title"] for it in win.library["categories"][apps_idx]["items"]]
            self.assertGreaterEqual(len(before_titles), 2)
            removed_title = before_titles[0]
            QTest.keyClick(win, Qt.Key_Delete)
            self.app.processEvents()
            after_titles = [it["title"] for it in win.library["categories"][apps_idx]["items"]]
            self.assertEqual(after_titles, before_titles[1:])
            # Persisted in library.json while other categories remain intact
            disk_lib = load_library(tmp_root / "data" / "library.json", tmp_root)
            self.assertEqual(len(disk_lib["categories"]), len(win.library["categories"]))
            self.assertNotIn(removed_title, [it["title"] for it in disk_lib["categories"][apps_idx]["items"]])

            # Add and remove a manual app + remove a library app inside Quick Launch
            QTest.keyClick(win, Qt.Key_F4)
            self.app.processEvents()
            manual_app = make_app("CustomApp", "/bin/custom-app", source="manual")
            win.launchpad.store.add_manual(manual_app)
            win.launchpad._reload(manual_app["id"])
            self.app.processEvents()
            self.assertEqual(win.launchpad.grid.current_app()["title"], "CustomApp")
            self.assertTrue(win.launchpad.remove_btn.isEnabled())
            win.launchpad._remove_selected()
            self.app.processEvents()
            self.assertFalse(win.launchpad.store.manual)

            # Removing a library app from Quick Launch updates MainWindow too
            win.launchpad._set_query(after_titles[0])
            self.app.processEvents()
            self.assertEqual(win.launchpad.grid.current_app()["source"], "library")
            win.launchpad._remove_selected()
            self.app.processEvents()
            final_titles = [it["title"] for it in win.library["categories"][apps_idx]["items"]]
            self.assertNotIn(after_titles[0], final_titles)

            win.force_quit()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
