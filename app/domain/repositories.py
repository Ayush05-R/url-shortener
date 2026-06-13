# Abstract URLRepository interface

from __future__ import annotations
from abc import ABC, abstractmethod
from app.domain.models import URLRecord


class URLRepository(ABC):
    @abstractmethod
    def save(self, record: URLRecord) -> URLRecord:
        """Persist a new URL record. Returns the saved record with any DB-assigned fields."""
        ...

    @abstractmethod
    def get_by_code(self, code: str) -> URLRecord | None:
        """Find a record by short code. Returns None if not found — never raises."""
        ...

    @abstractmethod
    def increment_clicks(self, code: str) -> None:
        """Increment click counter. Silently ignores unknown codes."""
        ...

    @abstractmethod
    def next_id(self) -> int:
        """Return the next available integer ID. Must be unique and monotonically increasing."""
        ...
