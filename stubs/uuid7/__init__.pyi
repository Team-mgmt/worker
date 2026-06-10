"""Type stubs for uuid7-standard - RFC 9562 compliant UUIDv7 implementation."""

from datetime import datetime
from uuid import UUID

def create(when: datetime | None = None) -> UUID:
    """Create a UUIDv7 with timestamp-based ordering.

    Args:
        when: Optional datetime for the timestamp. If None, uses current time.
              Can be naive (interpreted as local time) or timezone-aware.

    Returns:
        A UUID object with version 7.
    """
    ...

def time(u: UUID | str) -> datetime:
    """Extract the timestamp from a UUIDv7.

    Args:
        u: A UUID object or string representation of a UUIDv7.

    Returns:
        A timezone-aware datetime (UTC) extracted from the UUID.

    Raises:
        ValueError: If the UUID is not a valid UUIDv7.
    """
    ...
