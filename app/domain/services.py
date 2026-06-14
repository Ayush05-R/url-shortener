from app.algorithms.base62 import encode
from app.domain.models import URLRecord
from app.domain.repositories import URLRepository
from app.exceptions import URLNotFoundError


class URLService:
    def __init__(self, repo: URLRepository) -> None:
        self._repo = repo

    def shorten(self, original_url: str) -> URLRecord:
        record_id = self._repo.next_id()
        code = encode(record_id)
        record = URLRecord(
            id=record_id,
            original_url=original_url,
            code=code,
        )
        self._repo.save(record)
        return record

    def redirect(self, code: str) -> URLRecord:
        record = self._repo.get_by_code(code)
        if record is None:
            raise URLNotFoundError(code)
        self._repo.increment_clicks(code)
        return record

    def get_stats(self, code: str) -> URLRecord:
        record = self._repo.get_by_code(code)
        if record is None:
            raise URLNotFoundError(code)
        return record
