"""Share optional SunsetHue model-run checks across Home Assistant locations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from .api import (
    SunsetHueAuthError,
    SunsetHueClient,
    SunsetHueError,
    SunsetHueQuotaExceededError,
    SunsetHueRateLimitError,
)
from .const import RUN_INFO_CACHE_SECONDS
from .models import ModelRunInfo


class ModelRunMonitor:
    """Coalesce checks per API key, with short TTLs and no persisted credentials."""

    def __init__(self) -> None:
        self._cached: dict[str, tuple[datetime, ModelRunInfo | None]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def async_current(self, client: SunsetHueClient) -> ModelRunInfo | None:
        """Get the most recent provider run; return None for unknown contracts or outages."""
        key = client.run_info_cache_key
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = datetime.now(UTC)
            cached = self._cached.get(key)
            if cached is not None and cached[0] > now:
                return cached[1]

            try:
                info = await client.async_get_run_info()
            except (
                SunsetHueAuthError,
                SunsetHueQuotaExceededError,
                SunsetHueRateLimitError,
            ):
                raise
            except SunsetHueError:
                info = None

            expires = now + timedelta(seconds=RUN_INFO_CACHE_SECONDS)
            if info is not None and info.next_expected_update is not None and info.next_expected_update > now:
                expires = min(expires, info.next_expected_update)
            self._cached[key] = (expires, info)
            return info
