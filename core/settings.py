"""User settings persisted in data/settings.json."""
import json
import shutil
from pathlib import Path

DEFAULTS = {
    "slideshow_interval": 6,     # seconds per picture
    "start_fullscreen": True,
    "volume": 80,                # 0..100
    "resume_enabled": True,      # remember and offer resume points
    "scan_folders": [],          # folders the library scanner walks
    "program_folders": [],       # folders Quick Launch scans for apps
    "discover_apps": False,      # index installed applications (opt-in)
    "show_hidden": False,        # reveal private/hidden items
}


def ensure_settings(path: Path) -> None:
    """Copy settings.example.json to settings.json on first run."""
    if path.exists():
        return
    example = path.with_name("settings.example.json")
    try:
        if example.exists():
            shutil.copyfile(example, path)
    except OSError:
        pass


def load_settings(path: Path) -> dict:
    settings = dict(DEFAULTS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for key in DEFAULTS:
                if key in raw:
                    settings[key] = raw[key]
    except (OSError, json.JSONDecodeError):
        pass
    settings["slideshow_interval"] = max(1, int(settings["slideshow_interval"]))
    settings["volume"] = max(0, min(100, int(settings["volume"])))
    settings["resume_enabled"] = bool(settings["resume_enabled"])
    settings["scan_folders"] = [str(p) for p in settings["scan_folders"]]
    settings["program_folders"] = [str(p) for p in settings["program_folders"]]
    settings["discover_apps"] = bool(settings["discover_apps"])
    settings["start_fullscreen"] = bool(settings["start_fullscreen"])
    settings["show_hidden"] = bool(settings["show_hidden"])
    return settings


def save_settings(path: Path, settings: dict) -> None:
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
