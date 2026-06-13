# URLRecord dataclass

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class URLRecord:
    id: int
    code: str
    original_url: str
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    click_count: int = 0
