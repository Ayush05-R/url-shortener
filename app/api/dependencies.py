from __future__ import annotations
from fastapi import Request
from app.domain.services import URLService

def get_service(request: Request) -> URLService:
    return request.app.state.service