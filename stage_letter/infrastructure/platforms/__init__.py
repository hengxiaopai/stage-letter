"""Formal platform adapter infrastructure for Stage Letter."""

from .registry import AdapterNotFoundError, AdapterRegistry

__all__ = ["AdapterNotFoundError", "AdapterRegistry"]
