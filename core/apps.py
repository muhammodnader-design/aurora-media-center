"""Application discovery and launching for Quick Launch.

Everything here works with plain *applications* — Aurora never needs to know
what a program does. The module offers three cross-platform sources:

  * installed-app discovery (Start Menu shortcuts, XDG .desktop entries,
    macOS .app bundles),
  * user-chosen program folders, scanned for a likely main executable,
  * manual entries added with "Add app…".

All scanning is local and offline. Discovery is opt-in; program folders are
only read when the user adds them in Settings.
"""
import hashlib
import os
import plistlib
import re
import shlex
import shutil
import sys
from difflib import SequenceMatcher
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices

# Names that are almost never the program itself, only its helpers.
EXCLUDED_STEM = re.compile(
    r"^(unins|uninst|uninstall|setup|install|installer|dxweb|dxsetup|vcredist|"
    r"vc_redist|dotnetfx|oalinst|quicksfv|chromedriver|notification_helper|"
    r"python|pythonw|crash|crashreport|report|reporter|"
    r"update|updater|patcher?|register|eula|readme|license|website|help)$",
    re.IGNORECASE,
)
EXCLUDED_DIR = {
    "redist", "_redist", "_commonredist", "directx", "support", "install",
    "installers", "crash", "crashreport", "logs", "log", "cache", "__pycache__",
    "node_modules", "locales", "resources", "data", "tools", "editor",
}
NON_EXEC_SUFFIX = {
    ".dll", ".so", ".dylib", ".pdb", ".txt", ".md", ".json", ".ini", ".cfg",
    ".log", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".mp4", ".mkv",
    ".mp3", ".wav", ".zip", ".7z", ".rar", ".pak", ".dat", ".bin", ".pyc",
}
SKIP_SHORTCUT_WORDS = ("uninstall", "readme", "release notes", "website",
                       "documentation", "license", "changelog")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _clean_title(value: str) -> str:
    text = str(value or "").replace("_", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _norm(target: str) -> str:
    try:
        text = os.path.normpath(os.path.expanduser(str(target)))
    except (OSError, ValueError):
        return str(target)
    return text.lower() if sys.platform == "win32" else text


def app_id(target: str, args=None) -> str:
    """Stable short id for an app target (and optional arguments)."""
    key = _norm(target)
    if args:
        key += "\0" + "\0".join(str(a) for a in args)
    return hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()[:16]


def guess_kind(target: str) -> str:
    suffix = Path(str(target)).suffix.lower()
    if suffix == ".lnk":
        return "shortcut"
    if suffix == ".desktop":
        return "desktop"
    if suffix == ".app":
        return "bundle"
    if suffix in (".exe", ".bat", ".cmd", ".com"):
        return "exe"
    return "binary"


def make_app(title: str, target: str, kind: str = "", source: str = "",
             args=None, icon_name: str = "", description: str = "",
             hue=None) -> dict:
    """Build the plain-dict app entry used everywhere in the launcher."""
    target = str(target)
    args = [str(a) for a in (args or [])]
    aid = app_id(target, args)
    suffix = Path(target).suffix
    stem = suffix and Path(target).stem or Path(target).name
    return {
        "id": aid,
        "title": _clean_title(title) or _clean_title(stem) or target,
        "target": target,
        "args": args,
        "kind": kind or guess_kind(target),
        "source": source,
        "icon_name": str(icon_name or ""),
        "description": str(description or target),
        "hue": float(hue) if hue is not None else float(int(aid[:6], 16) % 360),
    }


def dedupe(apps) -> list:
    seen = set()
    unique = []
    for app in apps:
        aid = app.get("id")
        if not aid or aid in seen:
            continue
        seen.add(aid)
        unique.append(app)
    return unique


def sort_apps(apps) -> list:
    return sorted(apps, key=lambda a: a.get("title", "").casefold())


# ---------------------------------------------------------------------------
# launching
# ---------------------------------------------------------------------------
def _desktop_entry(path: Path) -> dict:
    """Read the [Desktop Entry] group of a .desktop file."""
    entry = {}
    group = ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return entry
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            continue
        if group != "Desktop Entry" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        entry[key.strip()] = value.strip()
    return entry


def _desktop_exec_tokens(exec_line: str) -> list:
    try:
        tokens = shlex.split(exec_line, posix=True)
    except ValueError:
        tokens = exec_line.split()
    cleaned = []
    for token in tokens:
        if re.fullmatch(r"%[fFuUdDnNickvm]", token):
            continue
        cleaned.append(token.replace("%%", "%"))
    return cleaned


def _launch_desktop(path: Path) -> bool:
    tokens = _desktop_exec_tokens(_desktop_entry(path).get("Exec", ""))
    if tokens:
        program = tokens[0]
        if "/" in program or Path(program).is_absolute():
            ok = QProcess.startDetached(program, tokens[1:], str(path.parent))
        else:
            found = shutil.which(program)
            ok = QProcess.startDetached(found or program, tokens[1:])
        if ok:
            return True
    if shutil.which("gio"):
        return QProcess.startDetached("gio", ["launch", str(path)])
    if shutil.which("gtk-launch"):
        return QProcess.startDetached("gtk-launch", [path.stem])
    return False


def _launch_bundle(path: Path) -> bool:
    if sys.platform == "darwin" and shutil.which("open"):
        return QProcess.startDetached("open", ["-a", str(path)])
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def launch_app(app: dict) -> tuple:
    """Launch an app entry. Returns (ok, message)."""
    target = str(app.get("target") or "").strip()
    title = _clean_title(app.get("title", "")) or Path(target).name or "app"
    if not target:
        return False, "This app has no launch target."
    args = [str(a) for a in (app.get("args") or [])]
    kind = app.get("kind") or guess_kind(target)
    path = Path(target)
    local = path.is_absolute() or "/" in target or "\\" in target
    if local and not path.exists():
        return False, f"Could not launch {title} — target not found"

    if kind == "shortcut":
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(target))
    elif kind == "desktop":
        ok = _launch_desktop(path)
    elif kind == "bundle":
        ok = _launch_bundle(path)
    else:
        workdir = str(path.parent) if path.parent.is_dir() else ""
        ok = QProcess.startDetached(target, args, workdir)
        if not ok:
            ok = QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    if ok:
        return True, f"Launched {title}"
    return False, f"Could not launch {title}"


# ---------------------------------------------------------------------------
# installed-app discovery
# ---------------------------------------------------------------------------
def _shortcut_ok(path: Path) -> bool:
    stem = path.stem.strip().lower()
    if EXCLUDED_STEM.match(stem):
        return False
    return not any(word in stem for word in SKIP_SHORTCUT_WORDS)


def _discover_windows() -> list:
    roots = []
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("PROGRAMDATA")
    home = Path.home()
    if appdata:
        roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if programdata:
        roots.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    roots.append(home / "Desktop")
    public = os.environ.get("PUBLIC")
    if public:
        roots.append(Path(public) / "Desktop")

    found = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            links = root.rglob("*.lnk")
        except OSError:
            continue
        for link in links:
            if not _shortcut_ok(link):
                continue
            found.append(make_app(link.stem, str(link), kind="shortcut",
                                  source="start-menu"))
    return sort_apps(found)


def _linux_app_roots() -> list:
    roots = [Path.home() / ".local" / "share" / "applications"]
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/share:/usr/local/share")
    for base in data_dirs.split(":"):
        if base:
            roots.append(Path(base) / "applications")
    roots += [Path("/usr/share/applications"), Path("/usr/local/share/applications")]
    unique = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def _discover_linux() -> list:
    found = []
    for root in _linux_app_roots():
        if not root.is_dir():
            continue
        try:
            files = root.rglob("*.desktop")
        except OSError:
            continue
        for path in files:
            entry = _desktop_entry(path)
            if not entry:
                continue
            if entry.get("Type", "Application") != "Application":
                continue
            if entry.get("NoDisplay", "").lower() == "true":
                continue
            if entry.get("Hidden", "").lower() == "true":
                continue
            name = entry.get("Name", "").strip() or path.stem
            if not _shortcut_ok(Path(name)):
                continue
            try_exec = entry.get("TryExec", "").strip()
            if try_exec and not (Path(try_exec).is_file() or shutil.which(try_exec)):
                continue
            if not entry.get("Exec", "").strip():
                continue
            found.append(make_app(name, str(path), kind="desktop",
                                  source="installed",
                                  icon_name=entry.get("Icon", ""),
                                  description=entry.get("Comment", "")))
    return sort_apps(found)


def _macos_bundle_meta(bundle: Path) -> tuple:
    """Read display title and icon path from Info.plist when available."""
    title = bundle.stem
    icon_name = ""
    plist_path = bundle / "Contents" / "Info.plist"
    if not plist_path.is_file():
        return title, icon_name
    try:
        with plist_path.open("rb") as fh:
            info = plistlib.load(fh)
    except Exception:
        return title, icon_name
    if isinstance(info, dict):
        name = str(info.get("CFBundleDisplayName")
                   or info.get("CFBundleName") or "").strip()
        if name:
            title = name
        icon_file = str(info.get("CFBundleIconFile") or "").strip()
        if icon_file:
            res = bundle / "Contents" / "Resources"
            cand = res / icon_file
            if not cand.is_file() and not cand.suffix:
                cand = res / f"{icon_file}.icns"
            if cand.is_file():
                icon_name = str(cand)
    return title, icon_name


def _discover_macos() -> list:
    roots = [Path("/Applications"), Path("/System/Applications"),
             Path.home() / "Applications"]
    roots += [root / "Utilities" for root in list(roots)]
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            bundles = list(root.glob("*.app"))
        except OSError:
            continue
        for bundle in bundles:
            if not _shortcut_ok(Path(bundle.stem)):
                continue
            title, icon_name = _macos_bundle_meta(bundle)
            found.append(make_app(title, str(bundle), kind="bundle",
                                  source="installed", icon_name=icon_name))
    return sort_apps(found)


def discover_apps(discover_installed: bool = True, program_folders=None) -> list:
    """Collect app entries from the requested sources. Never touches the UI."""
    apps = []
    if discover_installed:
        try:
            if sys.platform == "win32":
                apps += _discover_windows()
            elif sys.platform == "darwin":
                apps += _discover_macos()
            else:
                apps += _discover_linux()
        except Exception:
            pass
    apps += scan_program_folders(program_folders or [])
    return dedupe(apps)


# ---------------------------------------------------------------------------
# program folders
# ---------------------------------------------------------------------------
def _is_launchable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    suffix = path.suffix.lower()
    if suffix in (".exe", ".bat", ".cmd", ".com", ".lnk", ".appimage", ".run"):
        return True
    if sys.platform != "win32" and suffix not in NON_EXEC_SUFFIX:
        return os.access(path, os.X_OK)
    return False


def _skip_dir(name: str) -> bool:
    low = name.lower()
    return (name.startswith(".") or low in EXCLUDED_DIR
            or low.endswith(".app") and sys.platform != "darwin")


def _excluded_name(stem: str) -> bool:
    low = _clean_title(stem).lower()
    return bool(EXCLUDED_STEM.match(low)) or low in {"uninstall", "unins000"}


def _collect_candidates(root: Path, max_depth: int = 3) -> list:
    """Walk a program folder, treating *.app bundles as single programs."""
    candidates = []
    visited = 0

    def walk(folder: Path, depth: int):
        nonlocal visited
        if visited > 4000:
            return
        try:
            children = list(folder.iterdir())
        except OSError:
            return
        for child in children:
            visited += 1
            if visited > 4000:
                return
            if child.name.startswith("."):
                continue
            if child.is_dir():
                if child.suffix.lower() == ".app" and sys.platform == "darwin":
                    candidates.append(child)
                    continue
                if depth >= max_depth or _skip_dir(child.name):
                    continue
                walk(child, depth + 1)
            elif _is_launchable_file(child) and not _excluded_name(child.stem):
                candidates.append(child)

    walk(root, 0)
    return candidates


def _score_candidate(path: Path, folder: Path) -> float:
    stem = path.stem
    name = stem.lower()
    if _excluded_name(stem):
        return -1.0

    score = 0.0
    suffix = path.suffix.lower()
    if suffix == ".app":
        score += 60
    elif suffix == ".appimage":
        score += 50
    elif suffix == ".exe":
        score += 40
    elif suffix in (".bat", ".cmd", ".lnk"):
        score += 20
    elif suffix in (".run", ""):
        score += 15

    try:
        depth = max(0, len(path.relative_to(folder).parts) - 1)
    except ValueError:
        depth = 0
    score -= depth * 8

    folder_name = folder.name.lower()
    score += SequenceMatcher(None, name, folder_name).ratio() * 35
    if name.startswith(folder_name) or folder_name.startswith(name):
        score += 10
    if re.search(r"(launcher|start|play|run|boot|client)", name):
        score += 6
    if re.search(r"(server|dedicated|benchmark|config|tool|editor|crash)", name):
        score -= 12
    try:
        score += min(path.stat().st_size / 1_000_000, 25)
    except OSError:
        pass
    return score


def _best_in_tree(folder: Path) -> Path:
    scored = [(_score_candidate(p, folder), p)
              for p in _collect_candidates(folder)]
    scored = [(s, p) for s, p in scored if s >= 0]
    if not scored:
        return None
    scored.sort(key=lambda pair: (-pair[0], str(pair[1]).lower()))
    return scored[0][1]


def scan_program_folder(folder: Path) -> list:
    """Return one app per immediate subfolder, plus loose top-level programs."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    try:
        children = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []

    found = []
    loose = 0
    for child in children:
        if child.name.startswith("."):
            continue
        if child.is_file():
            if (_is_launchable_file(child) and not _excluded_name(child.stem)
                    and loose < 30):
                found.append(make_app(child.stem, str(child),
                                      source="program-folder"))
                loose += 1
            continue
        if _skip_dir(child.name):
            continue
        if child.suffix.lower() == ".app" and sys.platform == "darwin":
            title, icon_name = _macos_bundle_meta(child)
            found.append(make_app(title, str(child), kind="bundle",
                                  source="program-folder", icon_name=icon_name))
            continue
        best = _best_in_tree(child)
        if best is not None:
            found.append(make_app(child.name, str(best),
                                  source="program-folder"))
    return sort_apps(found)


def scan_program_folders(folders) -> list:
    found = []
    for folder in folders or []:
        try:
            found += scan_program_folder(Path(folder).expanduser())
        except OSError:
            continue
    return dedupe(found)


# ---------------------------------------------------------------------------
# library integration
# ---------------------------------------------------------------------------
def library_app_entries(library: dict, root: Path) -> list:
    """Turn app items already in data/library.json into launcher entries."""
    from .library import resolve_file

    found = []
    for category in library.get("categories", []):
        for item in category.get("items", []):
            if item.get("type") != "app" and category.get("id") != "apps":
                continue
            target = resolve_file(item, root)
            if not target:
                continue
            found.append(make_app(
                item.get("title", ""), target,
                kind=guess_kind(target), source="library",
                args=item.get("args") or [],
                description=item.get("description", ""),
                hue=item.get("hue")))
    return found
