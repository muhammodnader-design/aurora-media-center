"""Persistent Quick Launch state.

Two files are kept, both machine-local and gitignored:

  data/apps.json       cache of discovered / scanned apps
  data/launchpad.json  pins, recents, hidden ids, and manually added apps

Discovered apps are deliberately kept out of data/library.json so a scan can
never rewrite the user's curated library.
"""
import json
from pathlib import Path

from .apps import make_app

STATE_VERSION = 1
MAX_RECENT = 12


def _read_json(path: Path, fallback):
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return raw if isinstance(raw, dict) else fallback


def _normalize(raw) -> dict:
    if not isinstance(raw, dict):
        return None
    target = str(raw.get("target") or "").strip()
    if not target:
        return None
    app = make_app(
        raw.get("title", ""), target,
        kind=str(raw.get("kind") or ""),
        source=str(raw.get("source") or ""),
        args=raw.get("args") or [],
        icon_name=str(raw.get("icon_name") or ""),
        description=str(raw.get("description") or ""),
        hue=raw.get("hue"))
    icon = str(raw.get("icon") or "")
    if icon:
        app["icon"] = icon
    return app


def _normalize_list(raw) -> list:
    apps = []
    for entry in raw if isinstance(raw, list) else []:
        app = _normalize(entry)
        if app is not None:
            apps.append(app)
    return apps


def _id_list(raw) -> list:
    ids = []
    for value in raw if isinstance(raw, list) else []:
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)
    return ids


class AppStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.cache_path = self.data_dir / "apps.json"
        self.state_path = self.data_dir / "launchpad.json"
        self.icon_dir = self.data_dir / "app_icons"
        self.state_existed = False
        self.discovered = []
        self.sources = {}
        self.manual = []
        self.pinned = []
        self.recent = []
        self.hidden = []
        self.load()

    # ---- loading / saving ----
    def load(self):
        cache = _read_json(self.cache_path, {})
        self.discovered = _normalize_list(cache.get("apps"))
        sources = cache.get("sources")
        self.sources = sources if isinstance(sources, dict) else {}

        self.state_existed = self.state_path.exists()
        state = _read_json(self.state_path, {})
        self.manual = _normalize_list(state.get("manual"))
        self.pinned = _id_list(state.get("pinned"))
        self.recent = _id_list(state.get("recent"))[:MAX_RECENT]
        self.hidden = _id_list(state.get("hidden"))

    def save_cache(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {"version": STATE_VERSION, "sources": self.sources,
                   "apps": self.discovered}
        try:
            self.cache_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except OSError:
            pass

    def save_state(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": STATE_VERSION,
            "manual": self.manual,
            "pinned": self.pinned,
            "recent": self.recent,
            "hidden": self.hidden,
        }
        try:
            self.state_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except OSError:
            pass

    # ---- queries ----
    def merged(self, library_apps=None) -> list:
        """Manual apps, then library apps, then discovered apps."""
        seen = set()
        ordered = []
        for group in (self.manual, library_apps or [], self.discovered):
            for app in group:
                aid = app.get("id")
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                ordered.append(app)
        return ordered

    def by_id(self, apps, aid) -> dict:
        return next((app for app in apps if app.get("id") == aid), None)

    def selected(self, apps, ids) -> list:
        out = []
        for aid in ids:
            app = self.by_id(apps, aid)
            if app is not None:
                out.append(app)
        return out

    def pinned_apps(self, apps) -> list:
        return self.selected(apps, self.pinned)

    def recent_apps(self, apps, limit: int = 8) -> list:
        return self.selected(apps, self.recent)[:limit]

    def visible_apps(self, apps, show_hidden: bool) -> list:
        if show_hidden:
            return list(apps)
        hidden = set(self.hidden)
        return [app for app in apps if app.get("id") not in hidden]

    def is_pinned(self, aid: str) -> bool:
        return aid in self.pinned

    def is_hidden(self, aid: str) -> bool:
        return aid in self.hidden

    def icon_path(self, app: dict) -> Path:
        rel = str(app.get("icon") or f"app_icons/{app.get('id', 'app')}.png")
        path = Path(rel)
        return path if path.is_absolute() else self.data_dir / path

    def has_icon(self, app: dict) -> bool:
        try:
            return self.icon_path(app).is_file()
        except OSError:
            return False

    # ---- mutations ----
    def seed_pins(self, apps) -> bool:
        """Pin the library's curated apps on a brand-new launchpad."""
        if self.state_existed or self.pinned or not apps:
            return False
        self.pinned = [app["id"] for app in apps[:6]]
        self.save_state()
        return True

    def toggle_pin(self, aid: str) -> bool:
        if aid in self.pinned:
            self.pinned.remove(aid)
            pinned = False
        else:
            self.pinned.append(aid)
            pinned = True
        self.save_state()
        return pinned

    def hide(self, aid: str) -> None:
        if aid not in self.hidden:
            self.hidden.append(aid)
        if aid in self.pinned:
            self.pinned.remove(aid)
        if aid in self.recent:
            self.recent = [r for r in self.recent if r != aid]
        self.save_state()

    def unhide(self, aid: str) -> None:
        if aid in self.hidden:
            self.hidden.remove(aid)
            self.save_state()

    def record_launch(self, aid: str) -> None:
        if not aid or aid in self.hidden:
            return
        self.recent = [aid] + [r for r in self.recent if r != aid]
        self.recent = self.recent[:MAX_RECENT]
        self.save_state()

    def add_manual(self, app: dict) -> None:
        self.manual = [a for a in self.manual if a.get("id") != app.get("id")]
        self.manual.insert(0, app)
        self.save_state()

    def forget_id(self, aid: str) -> None:
        changed = False
        for name in ("pinned", "recent", "hidden"):
            lst = getattr(self, name)
            if aid in lst:
                setattr(self, name, [x for x in lst if x != aid])
                changed = True
        if changed:
            self.save_state()

    def remove_manual(self, aid: str) -> bool:
        before = len(self.manual)
        self.manual = [a for a in self.manual if a.get("id") != aid]
        if len(self.manual) == before:
            return False
        self.pinned = [p for p in self.pinned if p != aid]
        self.recent = [r for r in self.recent if r != aid]
        self.hidden = [h for h in self.hidden if h != aid]
        self.save_state()
        return True

    def set_discovered(self, apps, sources=None) -> None:
        self.discovered = list(apps)
        if sources is not None:
            self.sources = dict(sources)
        self.save_cache()
