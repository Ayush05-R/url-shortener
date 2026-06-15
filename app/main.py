# FastAPI app + lifespan

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.config import settings
from app.domain.memory import InMemoryURLRepository
from app.domain.services import URLService
from app.exceptions import URLNotFoundError


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.service = URLService(InMemoryURLRepository())
    # Startup initialize resources here in later phases (e.g., database connection pool, Redis client)
    yield
    # Shutdown cleanup here in later phases (e.g., close database connection pool, Redis client)


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)


@app.exception_handler(URLNotFoundError)
async def not_found_handler(request: Request, exc: URLNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": str(exc)},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


from app.api.routes.urls import router

app.include_router(router)
