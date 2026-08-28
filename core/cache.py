"""
File-based cache with 24-hour TTL, atomic writes, and advisory file locking.
Designed for single-instance deployments; shared volume needed for multi-instance.
"""

import json
import os
import time
import fcntl
from pathlib import Path
from typing import Any, Optional

from core.config import settings


def _ensure_cache_dir() -> None:
    """Ensure cache directory exists. Called on first use."""
    Path(settings.CACHE_DIR).mkdir(parents=True, exist_ok=True)


def _cache_path(key: str) -> Path:
    """Sanitize key and return full cache file path."""
    safe_key = "".join(c if c.isalnum() or c in "_-" else "_" for c in key)
    return Path(settings.CACHE_DIR) / f"{safe_key}.json"


def get_cached_response(key: str) -> Optional[Any]:
    """
    Read from cache if entry exists and is fresh (< TTL).
    Returns None on miss, expiry, or corruption.
    """
    _ensure_cache_dir()
    cache_file = _cache_path(key)
    if not cache_file.exists():
        return None

    try:
        with open(cache_file, "r") as f:
            # Advisory shared lock (Unix only; no-op on Windows)
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            except (AttributeError, OSError):
                pass  # Windows or unsupported

            # Re-check existence after acquiring lock (TOCTOU mitigation)
            if not cache_file.exists():
                return None

            # Check TTL
            mtime = os.path.getmtime(cache_file)
            age_seconds = time.time() - mtime
            if age_seconds > settings.CACHE_TTL_SECONDS:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except (AttributeError, OSError):
                    pass
                cache_file.unlink(missing_ok=True)
                return None

            try:
                data = json.load(f)
            except json.JSONDecodeError:
                # Corrupted cache file
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except (AttributeError, OSError):
                    pass
                cache_file.unlink(missing_ok=True)
                return None

            # Release lock
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (AttributeError, OSError):
                pass

            return data

    except OSError:
        return None


def set_cached_response(key: str, data: Any) -> bool:
    """
    Write data to cache with atomic replace and advisory exclusive lock.
    Returns True on success, False on failure.
    Never caches error payloads or empty values.
    """
    _ensure_cache_dir()
    # Reject invalid data
    if data is None or (isinstance(data, dict) and not data):
        return False

    # Reject error payloads (never cache throttled/error responses)
    if isinstance(data, dict):
        # Check for explicit error keys rather than substring matching
        if any(k in data for k in ("error", "error_message", "error_code", "detail")):
            return False

    cache_file = _cache_path(key)
    temp_file = cache_file.with_suffix(cache_file.suffix + ".tmp")

    try:
        # Write to temp file with exclusive lock
        with open(temp_file, "w") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except (AttributeError, OSError):
                pass

            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())

            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (AttributeError, OSError):
                pass

        # Atomic rename
        os.replace(temp_file, cache_file)
        return True

    except OSError:
        temp_file.unlink(missing_ok=True)
        return False


def invalidate_cache(key: str) -> bool:
    """Remove a specific cache entry. Returns True if existed."""
    cache_file = _cache_path(key)
    existed = cache_file.exists()
    cache_file.unlink(missing_ok=True)
    return existed


def clear_cache() -> int:
    """Remove all cache files. Returns count of removed files."""
    cache_dir = Path(settings.CACHE_DIR)
    if not cache_dir.exists():
        return 0

    count = 0
    for f in cache_dir.glob("*.json"):
        f.unlink(missing_ok=True)
        count += 1
    return count