from pathlib import Path

from ..config import REPO_ROOT


def default_cache_path() -> Path:
    return REPO_ROOT / ".cache" / "memstore.pkl"
