import json
import threading
from pathlib import Path


CACHE_FILE = Path(__file__).resolve().parent / "resolver_cache.json"
_CACHE_LOCK = threading.Lock()


def _normalize_lookup_key(name: str, directory: str) -> str:
    return f"{(name or '').strip().lower()}|{(directory or '').strip().lower()}"


def load_cache() -> dict:
    with _CACHE_LOCK:
        if not CACHE_FILE.exists():
            return {}
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}


def save_cache(data: dict) -> None:
    with _CACHE_LOCK:
        CACHE_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def get_cached_resolution(name: str, directory: str) -> dict | None:
    data = load_cache()
    return data.get(_normalize_lookup_key(name, directory))


def set_cached_resolution(name: str, directory: str, resolution: dict) -> None:
    data = load_cache()
    data[_normalize_lookup_key(name, directory)] = resolution
    save_cache(data)