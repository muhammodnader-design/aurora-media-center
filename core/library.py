"""Load and validate data/library.json."""
import json
import shutil
import sys
from pathlib import Path

DEFAULT_LIBRARY = {"categories": []}

_PLATFORM_KEY = {
    "win32": "file_windows",
    "linux": "file_linux",
    "darwin": "file_mac",
}.get(sys.platform, "")


def _candidates(value):
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value:
        return [value]
    return []


def resolve_file(item: dict, root: Path = None) -> str:
    """Resolve an item's playable path on this platform.

    Checks the platform-specific key first ("file_windows" / "file_linux" /
    "file_mac", string or list of candidates), then "file". Absolute paths
    are used as-is; relative paths resolve against the app root; bare names
    are looked up on PATH. Returns "" when nothing resolves.
    """
    candidates = _candidates(item.get(_PLATFORM_KEY)) + _candidates(item.get("file"))
    for cand in candidates:
        p = Path(cand)
        if p.is_absolute():
            if p.exists():
                return str(p)
            continue
        if root is not None and (root / cand).exists():
            return str(root / cand)
        found = shutil.which(cand)
        if found:
            return found
    return ""


def ensure_library(path: Path) -> None:
    """Create the editable library from the bundled example on first run.

    Keeps a fresh clone working out of the box while data/library.json stays
    personal and untracked.
    """
    if path.exists():
        return
    example = path.with_name("library.example.json")
    try:
        if example.exists():
            shutil.copyfile(example, path)
    except OSError:
        pass


def load_library(path: Path, root: Path = None) -> dict:
    """Read the library file, tolerating missing/broken JSON (hot-reload safe).

    Relative "art" paths are resolved against the app root so tiles can show
    custom cover images.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_LIBRARY
    root = root or path.parent.parent
    categories = []
    for cat in raw.get("categories", []):
        if not isinstance(cat, dict) or "id" not in cat:
            continue
        items = []
        for it in cat.get("items", []):
            if not isinstance(it, dict):
                continue
            art = str(it.get("art", ""))
            if art and not Path(art).is_absolute() and (root / art).exists():
                art = str(root / art)
            args = it.get("args", [])
            if isinstance(args, str):
                args = [args]
            elif not isinstance(args, list):
                args = []
            items.append({
                "title": str(it.get("title", "Untitled")),
                "meta": str(it.get("meta", "")),
                "description": str(it.get("description", "")),
                "hue": float(it.get("hue", 200)) % 360,
                "icon": str(it.get("icon", "◆")),
                "file": it.get("file", ""),
                "file_windows": it.get("file_windows", ""),
                "file_linux": it.get("file_linux", ""),
                "file_mac": it.get("file_mac", ""),
                "duration": float(it.get("duration", 180)),
                "type": str(it.get("type", "")),
                "scanned": bool(it.get("scanned", False)),
                "hidden": bool(it.get("hidden", False)),
                "art": art,
                "args": [str(a) for a in args],
            })
        categories.append({
            "id": str(cat["id"]),
            "label": str(cat.get("label", cat["id"].title())),
            "icon": str(cat.get("icon", "◆")),
            "items": items,
        })
    return {"categories": categories}


def save_library(path: Path, library: dict) -> None:
    path.write_text(json.dumps(library, indent=2, ensure_ascii=False), encoding="utf-8")


def prune_unavailable_scanned(library: dict, root: Path) -> int:
    """Drop scanned items whose files aren't present on this machine.

    Scanned entries (from F3 folder scans) are machine-specific: after
    copying the folder to another PC/VM their host paths must not show up
    as broken tiles. Manual items are kept — they intentionally fall back
    to simulated playback. Returns the number of removed items.
    """
    removed = 0
    for cat in library.get("categories", []):
        kept = []
        for it in cat.get("items", []):
            if it.get("scanned") and not resolve_file(it, root):
                removed += 1
            else:
                kept.append(it)
        cat["items"] = kept
    return removed


def hide_private_items(library: dict, show_hidden: bool) -> None:
    """Remove hidden items in place unless the privacy toggle is on."""
    if show_hidden:
        return
    for cat in library.get("categories", []):
        cat["items"] = [it for it in cat.get("items", []) if not it.get("hidden")]


def kind_for(item: dict, category_id: str) -> str:
    """Resolve playback kind: explicit item type wins, else category mapping."""
    explicit = item.get("type")
    if explicit in ("video", "audio", "pictures", "app"):
        return explicit
    return {
        "movies": "video",
        "tv": "video",
        "music": "audio",
        "pictures": "pictures",
        "apps": "app",
    }.get(category_id, "video")
