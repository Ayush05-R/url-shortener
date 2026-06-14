import pytest

from app.algorithms.base62 import decode
from app.exceptions import URLNotFoundError
from app.domain.repositories import URLRepository
from app.domain.memory import InMemoryURLRepository
from app.domain.services import URLService


def test_shorten_returns_record() -> None:
    repo: URLRepository = InMemoryURLRepository()
    service = URLService(repo)

    record = service.shorten("https://example.com")

    assert record.original_url == "https://example.com"
    assert record.code
    assert record.id == 1


def test_shorten_code_is_valid_base62() -> None:
    repo: URLRepository = InMemoryURLRepository()
    service = URLService(repo)

    record = service.shorten("https://example.com")

    assert decode(record.code) == record.id


def test_shorten_multiple_unique_codes() -> None:
    repo: URLRepository = InMemoryURLRepository()
    service = URLService(repo)

    record1 = service.shorten("https://a.com")
    record2 = service.shorten("https://b.com")
    record3 = service.shorten("https://c.com")

    codes = {record1.code, record2.code, record3.code}

    assert len(codes) == 3


def test_redirect_returns_record() -> None:
    repo: URLRepository = InMemoryURLRepository()
    service = URLService(repo)

    created = service.shorten("https://example.com")

    record = service.redirect(created.code)

    assert record is created


def test_redirect_increments_clicks() -> None:
    repo: URLRepository = InMemoryURLRepository()
    service = URLService(repo)

    record = service.shorten("https://example.com")

    assert record.click_count == 0

    service.redirect(record.code)

    assert record.click_count == 1

    service.redirect(record.code)

    assert record.click_count == 2


def test_redirect_unknown_code_raises() -> None:
    repo: URLRepository = InMemoryURLRepository()
    service = URLService(repo)

    with pytest.raises(URLNotFoundError):
        service.redirect("unknown")


def test_get_stats_returns_record() -> None:
    repo: URLRepository = InMemoryURLRepository()
    service = URLService(repo)

    created = service.shorten("https://example.com")

    record = service.get_stats(created.code)

    assert record is created


def test_get_stats_unknown_code_raises() -> None:
    repo: URLRepository = InMemoryURLRepository()
    service = URLService(repo)

    with pytest.raises(URLNotFoundError):
        service.get_stats("unknown")


def test_get_stats_does_not_increment() -> None:
    repo: URLRepository = InMemoryURLRepository()
    service = URLService(repo)

    record = service.shorten("https://example.com")

    service.get_stats(record.code)

    assert record.click_count == 0

    service.get_stats(record.code)

    assert record.click_count == 0
