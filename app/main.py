# FastAPI app + lifespan

from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup initialize resources here in later phases (e.g., database connection pool, Redis client)
    yield
    # Shutdown cleanup here in later phases (e.g., close database connection pool, Redis client)


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
