"""
File-based cache with 24-hour TTL, atomic writes, and advisory file locking.
Designed for single-instance deployments; shared volume needed for multi-instance.
"""

import json
import os
import fcntl
import tempfile
from pathlib import Path
from typing import Any, Optional

from core.config import settings


# Ensure cache directory exists
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
            age_seconds = os.time() - mtime if hasattr(os, "time") else 0
            if age_seconds > settings.CACHE_TTL_SECONDS:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN) if hasattr(fcntl, "LOCK_UN") else None
                cache_file.unlink(missing_ok=True)
                return None

            try:
                data = json.load(f)
            except json.JSONDecodeError:
                # Corrupted cache file
                fcntl.flock(f.fileno(), fcntl.LOCK_UN) if hasattr(fcntl, "LOCK_UN") else None
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
    # Reject invalid data
    if data is None or (isinstance(data, dict) and not data):
        return False

    # Reject error payloads (never cache throttled/error responses)
    if isinstance(data, dict):
        response_text = json.dumps(data).lower()
        if any(marker in response_text for marker in ["note", "information", "error message"]):
            return False

    cache_file = _cache_path(key)
    temp_file = Path(tempfile.gettempdir()) / f"{cache_file.name}.tmp"

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