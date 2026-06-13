# InMemoryURLRepository (dict-based, no db)

from __future__ import annotations
from app.domain.models import URLRecord
from app.domain.repositories import URLRepository


class InMemoryURLRepository(URLRepository):
    def __init__(self) -> None:
        self._store: dict[str, URLRecord] = {}
        self._counter: int = 0

    def save(self, record: URLRecord) -> URLRecord:
        self._store[record.code] = record
        return record

    def get_by_code(self, code: str) -> URLRecord | None:
        return self._store.get(code)

    def increment_clicks(self, code: str) -> None:
        if code in self._store:
            self._store[code].click_count += 1

    def next_id(self) -> int:
        self._counter += 1
        return self._counter
