import pytest

from app.domain.memory import InMemoryURLRepository
from app.domain.models import URLRecord
from app.domain.repositories import URLRepository


def test_save_and_retrieve() -> None:
    repo: URLRepository = InMemoryURLRepository()

    record = URLRecord(
        id=1,
        code="abc123",
        original_url="https://google.com",
    )

    repo.save(record)

    result = repo.get_by_code("abc123")

    assert result == record


def test_get_nonexistent_returns_none() -> None:
    repo: URLRepository = InMemoryURLRepository()

    result = repo.get_by_code("does-not-exist")

    assert result is None


def test_increment_clicks() -> None:
    repo: URLRepository = InMemoryURLRepository()

    record = URLRecord(
        id=1,
        code="abc123",
        original_url="https://google.com",
    )

    repo.save(record)

    repo.increment_clicks("abc123")

    result = repo.get_by_code("abc123")

    assert result is not None
    assert result.click_count == 1


def test_increment_nonexistent_code() -> None:
    repo: URLRepository = InMemoryURLRepository()

    repo.increment_clicks("missing-code")


def test_next_id_increments() -> None:
    repo: URLRepository = InMemoryURLRepository()

    assert repo.next_id() == 1
    assert repo.next_id() == 2
    assert repo.next_id() == 3


def test_cannot_instantiate_abstract() -> None:
    with pytest.raises(TypeError):
        URLRepository()
