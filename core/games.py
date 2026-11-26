"""Game detection: find launchable game executables in chosen folders.

Each immediate subfolder of a games folder is treated as one game (unless it
holds an executable at top level, in which case the folder itself is the
game). The best candidate .exe is picked with a simple heuristic that skips
installers/redistributables and prefers names matching the folder. On
Windows the exe's icon is extracted into data/covers for the tile art.

Adult-looking titles are flagged "hidden": true so they stay behind the
"Show private items" toggle in Settings.
"""
import hashlib
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from .library import load_library, save_library

EXCLUDED_STEM = re.compile(
    r"^(unins|uninst|setup|install|dxweb|dxsetup|vcredist|vc_redist|dotnetfx|"
    r"oalinst|quicksfv|chromedriver|notification_helper|python|pythonw|"
    r"crash|report|reporter|samp_debug|savegameeditor|hltv|hlds|rcon|"
    r"update|updater|patcher?|register|eula|readme)$",
    re.IGNORECASE,
)
EXCLUDED_DIR = {"redist", "_redist", "support", "directx", "_commonredist",
                "tools", "editor", "crash", "install", "installers"}
PRIVATE_HINTS = re.compile(
    r"(^|[ ._-])(ntr|hentai|nsfw|xxx|adult|lewd|sex|18\+)([ ._-]|$)"
    r"|summertimesaga|twisted prison|lust",
    re.IGNORECASE,
)
TAG_SUFFIXES = [
    "steamrip com", "steamrip", "ankergames", "fitgirl", "repack", "gog",
    "plaza", "codex", "skidrow", "goldberg", "empress", "elamigos",
]
TITLE_JUNK = re.compile(r"\bv\d+([ .]\d+)*\b|\b0[ .]\d+([ .]\d+)+\b", re.IGNORECASE)


def _hue_for(text: str) -> int:
    return int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16) % 360


def _clean_title(folder_name: str) -> str:
    title = folder_name.replace(".", " ").replace("_", " ")
    # hyphens survive inside words (Half-Life) but not next to digits/spaces
    title = re.sub(r"(?<![A-Za-z])-|-(?![A-Za-z])", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    low = title.lower()
    for tag in TAG_SUFFIXES:
        if low.endswith(tag):
            title = title[: len(title) - len(tag)].rstrip(" -_.")
            low = title.lower()
    title = TITLE_JUNK.sub("", title).strip(" -_.")
    # drop an installer-ish trailing "pc" / "win64" marker
    title = re.sub(r"\s+(pc|windows|win64|win32)$", "", title, flags=re.IGNORECASE)
    return title or folder_name


def _exe_candidates(folder: Path):
    out = []
    for exe in folder.rglob("*.exe"):
        rel = exe.relative_to(folder)
        if len(rel.parts) > 4:
            continue
        if any(part.lower() in EXCLUDED_DIR for part in rel.parts[:-1]):
            continue
        if EXCLUDED_STEM.match(exe.stem):
            continue
        try:
            size = exe.stat().st_size
        except OSError:
            continue
        if size < 6 * 1024:  # tiny stubs are rarely the game itself
            continue
        out.append((exe, rel, size))
    return out


def _score(exe: Path, rel: Path, size: int, folder_name: str) -> float:
    stem_norm = re.sub(r"[^a-z0-9]", "", exe.stem.lower())
    folder_norm = re.sub(r"[^a-z0-9]", "", folder_name.lower())
    similarity = SequenceMatcher(None, stem_norm, folder_norm).ratio() if stem_norm else 0
    if stem_norm and folder_norm and (folder_norm in stem_norm or stem_norm in folder_norm):
        similarity = max(similarity, 0.9)
    score = similarity * 100
    score += min(size / (1024 * 1024), 300) * 0.4
    if rel.parts and len(rel.parts) == 1:
        score += 80  # games normally ship their main exe at the folder root
    score -= (len(rel.parts) - 1) * 6
    if "game" in stem_norm:
        score += 15
    if "64" in stem_norm:
        score += 5
    return score


def _find_game_exe(folder: Path):
    candidates = _exe_candidates(folder)
    if not candidates:
        return None
    return max(candidates, key=lambda c: _score(c[0], c[1], c[2], folder.name))


def _top_level_exe(folder: Path):
    candidates = [c for c in _exe_candidates(folder) if len(c[1].parts) == 1]
    if not candidates:
        return None
    return max(candidates, key=lambda c: _score(c[0], c[1], c[2], folder.name))


def _name_matches(exe_stem: str, folder_name: str) -> bool:
    a = re.sub(r"[^a-z0-9]", "", exe_stem.lower())
    b = re.sub(r"[^a-z0-9]", "", folder_name.lower())
    return bool(a and b and (a in b or b in a))


def _discover_game_dir(folder: Path):
    """Return the subfolder that directly holds a game's main exe, or None."""
    children = [p for p in folder.iterdir()
                if p.is_dir() and p.name.lower() not in EXCLUDED_DIR]
    if _top_level_exe(folder):
        return folder
    hits = [c for c in children if _top_level_exe(c)]
    if len(hits) == 1:
        return hits[0]
    if _find_game_exe(folder):
        return folder
    if len(hits) > 1:
        return None
    deep = [c for c in children if _find_game_exe(c)]
    return deep[0] if len(deep) == 1 else None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "game"


def _extract_icon(exe: Path, covers: Path, name: str) -> str:
    """Windows only: save the exe icon as a PNG for the tile art."""
    if sys.platform != "win32":
        return ""
    try:
        from PySide6.QtCore import QFileInfo, QSize
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QFileIconProvider
        if QApplication.instance() is None:
            return ""
        icon = QFileIconProvider().icon(QFileInfo(str(exe)))
        if not isinstance(icon, QIcon) or icon.isNull():
            return ""
        pm = icon.pixmap(QSize(256, 256))
        if pm.isNull() or pm.width() < 16:
            return ""
        covers.mkdir(parents=True, exist_ok=True)
        out = covers / f"{_slug(name)}.png"
        if pm.save(str(out), "PNG"):
            return f"data/covers/{out.name}"
    except Exception:
        pass
    return ""


def detect_games(folders, covers: Path = None) -> list:
    """Return game items for all folders (no duplicate executables)."""
    covers = covers or Path("data") / "covers"
    games, seen = [], set()
    for folder in folders:
        root = Path(folder)
        if not root.is_dir():
            continue
        # Discover game folders: prefer the root itself when its top-level
        # exe is named like the folder, otherwise look one level down and
        # finally treat each child as a game (a collection folder).
        entries = []
        root_exe = _top_level_exe(root)
        if root_exe and _name_matches(root_exe[0].stem, root.name):
            entries = [root]
        else:
            for child in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name):
                found_dir = _discover_game_dir(child)
                if found_dir and found_dir not in entries:
                    entries.append(found_dir)
            if not entries and root_exe:
                entries = [root]
        for game_dir in entries:
            found = _find_game_exe(game_dir)
            if not found:
                continue
            exe, rel, size = found
            if exe in seen:
                continue
            seen.add(exe)
            title = _clean_title(game_dir.name)
            hidden = bool(PRIVATE_HINTS.search(game_dir.name))
            meta = f"Game • {size / (1024 * 1024):.0f} MB"
            games.append({
                "title": title,
                "meta": meta,
                "description": f"Launch {exe.name} from {game_dir.name}.",
                "hue": _hue_for(title),
                "icon": "🎮",
                "file": str(exe),
                "duration": 180,
                "scanned": True,
                "hidden": hidden,
                # no extracted icon for private items: keep the folder neutral
                "art": "" if hidden else _extract_icon(exe, covers, title),
            })
    return games


def scan_games(library_path: Path, folders, covers: Path = None) -> int:
    """Merge detected games into the library's games category."""
    games = detect_games(folders, covers)
    library = load_library(library_path)
    cat = next((c for c in library["categories"] if c["id"] == "games"), None)
    if cat is None:
        cat = {"id": "games", "label": "Video Games", "icon": "🎮", "items": []}
        apps = next((i for i, c in enumerate(library["categories"])
                     if c["id"] == "apps"), None)
        if apps is None:
            library["categories"].append(cat)
        else:
            library["categories"].insert(apps, cat)
    manual = [it for it in cat["items"] if not it.get("scanned")]
    cat["items"] = manual + games
    save_library(library_path, library)
    return len(games)
