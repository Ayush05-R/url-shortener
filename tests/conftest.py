import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.domain.memory import InMemoryURLRepository
from app.domain.services import URLService


@pytest.fixture
async def client():
    app.state.service = URLService(repo=InMemoryURLRepository())
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
