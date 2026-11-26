"""Resume points for long media, stored per machine in data/resume.json.

The key is the resolved absolute file path, so points stay meaningful when
library titles are edited and never leak between machines.
"""
import json
from pathlib import Path

MIN_RESUME = 10.0   # seconds; shorter positions are not worth offering
TAIL = 15.0         # forget the point this close to the end of the file


def key_for_file(file: str) -> str:
    if not file:
        return ""
    try:
        return str(Path(file).resolve())
    except OSError:
        return str(file)


def load_resume(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    points = {}
    for key, value in raw.items():
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            points[str(key)] = seconds
    return points


def save_resume(path: Path, points: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        clean = {k: round(float(v), 1) for k, v in points.items() if v > 0}
        path.write_text(json.dumps(clean, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    except OSError:
        pass


class ResumeStore:
    """Small wrapper that knows when a position is worth remembering."""

    def __init__(self, path: Path):
        self.path = path
        self.points = load_resume(path)

    def get(self, key: str) -> float:
        return self.points.get(key, 0.0)

    def update(self, key: str, pos: float, dur: float) -> bool:
        """Store/forget a point. Returns True when the stored set changed."""
        if not key:
            return False
        tail = min(TAIL, max(2.0, dur * 0.05))
        if pos >= MIN_RESUME and dur > 0 and pos < dur - tail:
            if abs(self.points.get(key, -1.0) - pos) < 1.0:
                return False
            self.points[key] = pos
        elif key in self.points:
            del self.points[key]
        else:
            return False
        save_resume(self.path, self.points)
        return True

    def clear_all(self) -> None:
        self.points.clear()
        save_resume(self.path, self.points)
