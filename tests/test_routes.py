import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_shorten_returns_201_with_code(client: AsyncClient):
    response = await client.post(
        "/shorten",
        json={"url": "https://example.com"},
    )

    assert response.status_code == 201

    data = response.json()

    assert "code" in data
    assert data["code"] != ""


@pytest.mark.asyncio
async def test_shorten_invalid_url_returns_422(
    client: AsyncClient,
):
    response = await client.post(
        "/shorten",
        json={"url": "not-a-url"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_redirect_known_code_returns_302(
    client: AsyncClient,
):
    create = await client.post(
        "/shorten",
        json={"url": "https://example.com"},
    )

    code = create.json()["code"]

    response = await client.get(
        f"/{code}",
        follow_redirects=False,
    )

    assert response.status_code == 302


@pytest.mark.asyncio
async def test_redirect_unknown_code_returns_404(
    client: AsyncClient,
):
    response = await client.get(
        "/does-not-exist",
        follow_redirects=False,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_redirect_follows_to_original_url(
    client: AsyncClient,
):
    original = "https://example.com/some/path"

    create = await client.post(
        "/shorten",
        json={"url": original},
    )

    code = create.json()["code"]

    response = await client.get(
        f"/{code}",
        follow_redirects=False,
    )

    assert response.headers["location"] == original


@pytest.mark.asyncio
async def test_stats_known_code_returns_200(
    client: AsyncClient,
):
    create = await client.post(
        "/shorten",
        json={"url": "https://example.com"},
    )

    code = create.json()["code"]

    response = await client.get(
        f"/stats/{code}",
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_stats_unknown_code_returns_404(
    client: AsyncClient,
):
    response = await client.get(
        "/stats/does-not-exist",
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stats_click_count_increases_after_redirect(
    client: AsyncClient,
):
    create = await client.post(
        "/shorten",
        json={"url": "https://example.com"},
    )

    code = create.json()["code"]

    before = await client.get(
        f"/stats/{code}",
    )

    before_count = before.json()["click_count"]

    await client.get(
        f"/{code}",
        follow_redirects=False,
    )

    after = await client.get(
        f"/stats/{code}",
    )

    after_count = after.json()["click_count"]

    assert after_count == before_count + 1
