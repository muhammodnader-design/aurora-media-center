"""Read the external Qt stylesheet."""
from pathlib import Path


def load_stylesheet(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
