from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from app.api.dependencies import get_service
from app.api.schemas import ShortenRequest, ShortenResponse, StatsResponse
from app.domain.services import URLService
from app.config import settings

router = APIRouter()


@router.post(
    "/shorten", response_model=ShortenResponse, status_code=status.HTTP_201_CREATED
)
async def shorten_url(body: ShortenRequest, service: URLService = Depends(get_service)):
    record = service.shorten(str(body.url))
    return ShortenResponse(
        code=record.code,
        short_url=f"{settings.base_url}/{record.code}",
        original_url=str(record.original_url),
    )


@router.get("/stats/{code}", response_model=StatsResponse)
async def get_stats(code: str, service: URLService = Depends(get_service)):
    record = service.get_stats(code)
    return StatsResponse(
        code=record.code,
        original_url=str(record.original_url),
        click_count=record.click_count,
        created_at=record.created_at.isoformat(),
    )


@router.get("/{code}")
async def redirect(code: str, service: URLService = Depends(get_service)):
    record = service.redirect(code)
    return RedirectResponse(
        url=str(record.original_url),
        status_code=302,
    )
