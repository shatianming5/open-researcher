"""Atomic file IO utilities — compatibility re-export.

This module has been migrated to ``open_researcher.plugins.storage.file_ops``.
This file re-exports all public names for backward compatibility.
"""

from open_researcher.plugins.storage.file_ops import (  # noqa: F401
    atomic_write_json,
    atomic_write_text,
    locked_append_text,
    locked_read_json,
    locked_update_json,
)
