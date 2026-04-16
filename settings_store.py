"""Persist user-adjustable settings (SL/TP etc.) to settings.json."""
import json
import os
from tempfile import NamedTemporaryFile

_PATH = os.path.join(os.path.dirname(__file__), "settings.json")


def load() -> dict:
    if not os.path.exists(_PATH):
        return {}
    try:
        with open(_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(data: dict):
    existing = load()
    existing.update(data)
    with NamedTemporaryFile("w", delete=False, dir=os.path.dirname(_PATH), encoding="utf-8") as tmp:
        json.dump(existing, tmp, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, _PATH)


def get(key: str, default):
    return load().get(key, default)
