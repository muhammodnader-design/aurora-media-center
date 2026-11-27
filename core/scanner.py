"""Folder scanner: fills data/library.json from user-chosen directories.

Manual items (no "scanned" flag) are preserved; previously scanned items
are replaced on each scan. The apps category is never touched.
"""
import hashlib
import re
from pathlib import Path

from .library import load_library, save_library

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".mpg", ".mpeg"}
AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".wma", ".opus"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}

_TV_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:tv|series|seasons?|shows?|episodes?|s\d{1,2})(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)
ICONS = {"movies": "🎬", "tv": "📺", "music": "🎵", "pictures": "🖼"}


def _hue_for(text: str) -> int:
    return int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16) % 360


def _is_mpeg_ts(path: Path) -> bool:
    """Distinguish MPEG transport streams from TypeScript (.ts) source files."""
    try:
        with path.open("rb") as fh:
            head = fh.read(189)
    except OSError:
        return False
    if len(head) < 1 or head[0] != 0x47:
        return False
    return len(head) < 189 or head[188] == 0x47


def _classify(path: Path):
    ext = path.suffix.lower()
    if ext in VIDEO_EXTS or (ext == ".ts" and _is_mpeg_ts(path)):
        if any(_TV_RE.search(part) for part in path.parts[:-1]):
            return "tv"
        return "movies"
    if ext in AUDIO_EXTS:
        return "music"
    if ext in IMAGE_EXTS:
        return "pictures"
    return None


def _make_item(path: Path, cat_id: str) -> dict:
    title = path.stem.replace(".", " ").replace("_", " ").strip() or path.name
    size_mb = path.stat().st_size / (1024 * 1024)
    meta = f"{path.suffix.lstrip('.').upper()} • {size_mb:.1f} MB"
    if cat_id in ("movies", "tv"):
        meta = f"Local video • {meta}"
    elif cat_id == "music":
        meta = f"Local audio • {meta}"
    else:
        meta = f"Local image • {meta}"
    return {
        "title": title,
        "meta": meta,
        "description": str(path),
        "hue": _hue_for(title),
        "icon": ICONS.get(cat_id, "◆"),
        "file": str(path),
        "scanned": True,
    }


def scan_into_library(library_path: Path, folders) -> dict:
    """Walk folders, merge results into library.json. Returns per-category counts."""
    found = {"movies": [], "tv": [], "music": [], "pictures": []}
    seen = set()
    for folder in folders:
        root = Path(folder)
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path in seen:
                continue
            cat_id = _classify(path)
            if cat_id is None:
                continue
            seen.add(path)
            try:
                found[cat_id].append(_make_item(path, cat_id))
            except OSError:
                continue

    library = load_library(library_path)
    by_id = {c["id"]: c for c in library["categories"]}
    for cat_id, items in found.items():
        if cat_id not in by_id:
            cat = {"id": cat_id, "label": cat_id.title(), "icon": ICONS[cat_id], "items": []}
            library["categories"].append(cat)
            by_id[cat_id] = cat
        cat = by_id[cat_id]
        manual = [it for it in cat["items"] if not it.get("scanned")]
        cat["items"] = manual + items
    save_library(library_path, library)
    return {cat_id: len(items) for cat_id, items in found.items()}
