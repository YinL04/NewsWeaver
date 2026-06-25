"""Memory compaction entry points."""

from .trends import auto_compact_memory, compact_all_recent


def compact_memory(topic_name: str, force: bool = False) -> int:
    """Compact L2 records into L3 weekly trends."""
    if force:
        return compact_all_recent(topic_name)
    return auto_compact_memory(topic_name)
