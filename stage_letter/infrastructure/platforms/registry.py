"""Registry for formal platform adapter implementations."""
from __future__ import annotations

from stage_letter.application.platforms import LivePlatformAdapter


class AdapterNotFoundError(LookupError):
    """Raised when no formal adapter is registered for a platform."""


class AdapterRegistry:
    """Explicit platform -> adapter mapping owned by the infrastructure layer."""

    def __init__(self) -> None:
        self._adapters: dict[str, LivePlatformAdapter] = {}

    def register(self, platform: str, adapter: LivePlatformAdapter) -> None:
        key = platform.strip()
        if not key:
            raise ValueError("platform is required")
        if key in self._adapters:
            raise ValueError(f"adapter already registered for {key!r}")
        if not isinstance(adapter, LivePlatformAdapter):
            raise TypeError("adapter does not implement LivePlatformAdapter")
        self._adapters[key] = adapter

    def get(self, platform: str) -> LivePlatformAdapter:
        key = platform.strip()
        if not key:
            raise ValueError("platform is required")
        try:
            return self._adapters[key]
        except KeyError as exc:
            raise AdapterNotFoundError(key) from exc

    def contains(self, platform: str) -> bool:
        key = platform.strip()
        return bool(key) and key in self._adapters

    def platforms(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))
