import time


class TTLCache:
    """
    Minimal in-memory TTL cache. Good enough to keep multiple users asking
    about the same symbol within a short window from each burning a separate
    call against a rate-limited external API. Swap for Redis if you run more
    than one app instance and want the cache shared across them.
    """

    def __init__(self, ttl_seconds: int = 30):
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: object) -> None:
        self._store[key] = (time.time() + self.ttl, value)


stock_price_cache = TTLCache(ttl_seconds=30)
