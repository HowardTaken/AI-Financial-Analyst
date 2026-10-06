"""Tiny thread-safe in-memory TTL cache so repeated runs don't re-hit SEC / Yahoo / Gemini."""

import functools
import threading
import time


def ttl_cache(seconds: float):
    """Cache a function's return value per (args, kwargs) for `seconds`. Exceptions are not cached."""

    def decorator(fn):
        store: dict = {}
        lock = threading.Lock()

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with lock:
                hit = store.get(key)
                if hit and hit[0] > now:
                    return hit[1]
            value = fn(*args, **kwargs)
            with lock:
                store[key] = (now + seconds, value)
            return value

        wrapper.cache_clear = store.clear
        return wrapper

    return decorator
