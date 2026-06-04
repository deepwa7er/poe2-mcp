"""Build-aware vendor-regex generation."""

from .compiler import build_regex
from .keywords import FRAGMENTS, SLOT_ALLOWED, slot_key
from .profile import Priority, derive_priorities

__all__ = [
    "FRAGMENTS",
    "Priority",
    "SLOT_ALLOWED",
    "build_regex",
    "derive_priorities",
    "slot_key",
]
