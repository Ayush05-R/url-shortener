# Phase 5 — API Routes
### URL Shortener Build Log

> This document explains everything built in Phase 5 — Pydantic schemas, FastAPI
> routing, dependency injection, exception handlers, HTTP semantics, and every
> mistake made and why it mattered. Also includes a complete code reference for
> every new file introduced in this phase.

---

## Table of Contents

1. [What Phase 5 Builds](#1-what-phase-5-builds)
2. [The API Layer — Its One Job](#2-the-api-layer)
3. [Pydantic Schemas — Request and Response Models](#3-pydantic-schemas)
4. [FastAPI Routing — How Routes Work Internally](#4-fastapi-routing)
5. [Dependency Injection in FastAPI — `Depends()`](#5-dependency-injection)
6. [Exception Handlers — Domain Errors to HTTP Errors](#6-exception-handlers)
7. [HTTP Semantics — Status Codes and Redirects](#7-http-semantics)
8. [Route Order — Why `/stats/{code}` Must Come Before `/{code}`](#8-route-order)
9. [Integration Tests vs Unit Tests](#9-integration-tests-vs-unit-tests)
10. [Mistakes Made in This Phase](#10-mistakes-made)
11. [Code Reference — `app/api/schemas.py`](#11-code-reference-schemas)
12. [Code Reference — `app/api/dependencies.py`](#12-code-reference-dependencies)
13. [Code Reference — `app/api/routes/urls.py`](#13-code-reference-routes)
14. [Code Reference — `app/main.py` (updated)](#14-code-reference-main)
15. [Code Reference — `tests/conftest.py` (updated)](#15-code-reference-conftest)
16. [Code Reference — `tests/test_routes.py`](#16-code-reference-test-routes)
17. [What Phase 5 Does NOT Have Yet](#17-what-phase-5-does-not-have-yet)
18. [Phase 6 Preview](#18-phase-6-preview)

---

## 1. What Phase 5 Builds

```
app/api/schemas.py          → Pydantic request/response models
app/api/dependencies.py     → Depends() functions
app/api/routes/urls.py      → Three HTTP routes
app/main.py                 → Updated: service on app.state, exception handler, router included
tests/conftest.py           → Updated: fresh service per test
tests/test_routes.py        → 8 integration tests
```

8 passing tests. Total: 50 passing across all five phases.

This is the first phase where the app is actually usable — you can run it with
`uvicorn app.main:app --reload` and make real HTTP requests.

---

## 2. The API Layer — Its One Job

The API layer has exactly one job: **translate between HTTP and the domain.**

```
HTTP request → Pydantic validates → Route calls service → Map result → HTTP response
```

What it does NOT do:
- Business logic (belongs in `URLService`)
- Database queries (belongs in repositories)
- Exception logic (domain raises exceptions, handler converts them)

If a route function is longer than 10 lines, something from a lower layer has
leaked into it. Routes should be thin translators, not logic containers.

### The Translation Pattern

Every route follows the same pattern:

```python
async def some_route(body: InputSchema, service = Depends(get_service)):
    # 1. Call the service with domain-appropriate input
    record = service.some_operation(str(body.field))

    # 2. Map the domain result (URLRecord) to an HTTP response schema
    return OutputSchema(
        field_a=record.field_a,
        field_b=str(record.field_b),
    )
```

The service speaks domain language (`URLRecord`). The route speaks HTTP language
(`ShortenResponse`, `StatsResponse`, `RedirectResponse`). The route is the translator.

---

## 3. Pydantic Schemas

### What They Are

Pydantic models are classes that describe the shape of data and validate it
automatically. FastAPI uses them for:

- **Request bodies** — validate incoming JSON before your code runs
- **Response models** — validate and serialize outgoing data to JSON

If validation fails on a request, FastAPI returns a `422 Unprocessable Entity`
automatically — your route handler never runs.

### `ShortenRequest`

```python
class ShortenRequest(BaseModel):
    url: HttpUrl
```

`HttpUrl` is a pydantic type that validates the value is a properly formatted
HTTP or HTTPS URL. It rejects:

```
"not-a-url"           → 422 — no scheme
"ftp://example.com"   → 422 — not HTTP/HTTPS
"http://"             → 422 — no host
"https://example.com" → ✓ valid
```

This validation happens before your route function is called. Zero lines of
validation code needed in the route.

**The `HttpUrl` trailing slash behaviour:**

Pydantic v2's `HttpUrl` normalises bare domain URLs by adding a trailing slash:

```python
url = HttpUrl("https://example.com")
str(url)  # → "https://example.com/"  (trailing slash added)

url = HttpUrl("https://example.com/path")
str(url)  # → "https://example.com/path"  (no change — already has path)
```

This is why tests using bare domains like `"https://example.com"` break when
checking the `location` header — pydantic stored it as `"https://example.com/"`.
The fix is to use URLs with paths in tests: `"https://example.com/some/path"`.

### `ShortenResponse`

```python
class ShortenResponse(BaseModel):
    code: str
    short_url: str
    original_url: str
```

`short_url` is a field that doesn't exist on `URLRecord` — it has to be built
in the route using the config's `base_url`:

```python
short_url=f"{settings.base_url}/{record.code}"
```

This is why you can't return the `URLRecord` directly from the shorten route —
the response schema has a different shape from the domain model.

### `StatsResponse`

```python
class StatsResponse(BaseModel):
    code: str
    original_url: str
    click_count: int
    created_at: str
```

`created_at` is a `str` not `datetime`. The domain model stores a `datetime`
object — the route converts it to an ISO 8601 string with `.isoformat()`:

```python
created_at=record.created_at.isoformat()
# → "2026-06-15T12:34:56.789012+00:00"
```

ISO 8601 is the universal standard for datetime strings in APIs. It's unambiguous,
timezone-aware, and parseable by every language and library.

---

## 4. FastAPI Routing

### `APIRouter`

```python
from fastapi import APIRouter

router = APIRouter()
```

`APIRouter` is a mini-application that groups related routes. Instead of defining
all routes directly on `app`, you define them on `router` and register the router
with `app`:

```python
# In urls.py
router = APIRouter()

@router.post("/shorten")
async def shorten_url(...):
    ...

# In main.py
from app.api.routes.urls import router
app.include_router(router)
```

Benefits:
- Routes are split across files — not one giant `main.py`
- Routers can have shared prefixes, tags, and middleware
- Easy to add versioning: `app.include_router(router, prefix="/v1")`

### `@router.post("/shorten")`

```python
@router.post(
    "/shorten",
    response_model=ShortenResponse,
    status_code=status.HTTP_201_CREATED
)
async def shorten_url(body: ShortenRequest, service: URLService = Depends(get_service)):
    ...
```

**`response_model=ShortenResponse`** — FastAPI validates the return value against
this schema. If the route returns something that doesn't match, FastAPI raises a
500 error. Also tells FastAPI what to include in the Swagger UI documentation.

**`status_code=status.HTTP_201_CREATED`** — the default status code for this route
is 201. Without this, FastAPI defaults to 200. POST that creates a resource should
return 201 — this is HTTP convention.

**`body: ShortenRequest`** — FastAPI sees this parameter is a Pydantic model and
automatically:
- Reads the request body as JSON
- Validates it against `ShortenRequest`
- Returns 422 if validation fails
- Passes the validated object to your function

**`service: URLService = Depends(get_service)`** — see Section 5.

### `@router.get("/{code}")`

```python
@router.get("/{code}")
async def redirect(code: str, service: URLService = Depends(get_service)):
    ...
```

`{code}` is a **path parameter**. FastAPI extracts the value from the URL path
and passes it to the function:

```
GET /aB3xY7z  →  code = "aB3xY7z"
GET /1         →  code = "1"
```

The `code: str` type hint tells FastAPI to treat it as a string. If you used
`code: int`, FastAPI would try to convert it and return 422 for non-integer codes.

---

## 5. Dependency Injection in FastAPI

### `Depends()`

```python
from fastapi import Depends

service: URLService = Depends(get_service)
```

`Depends(get_service)` tells FastAPI: "call `get_service` before this route runs
and inject its return value as `service`."

`get_service` is the dependency function:

```python
def get_service(request: Request) -> URLService:
    return request.app.state.service
```

FastAPI calls this automatically, passing the current `Request`. It returns the
`URLService` from `app.state`, which was initialized in `lifespan`.

### Why This Is Powerful

**In production:** `get_service` returns the real service with `InMemoryURLRepository`
(Phase 5) or `PostgresURLRepository` (Phase 6).

**In tests:** override the dependency to inject anything you want:

```python
app.dependency_overrides[get_service] = lambda: URLService(MockRepository())
```

One line swaps the service for every route in the app during tests. No monkey
patching. No global state mutation. Clean.

### The Full Dependency Chain

```
FastAPI receives request
    → calls get_service(request)
    → returns request.app.state.service   (URLService instance)
    → injects into route function as `service`
    → route calls service.shorten(...)
```

All of this happens before your route function body runs. By the time you're
inside the function, `service` is ready to use.

---

## 6. Exception Handlers

### The Problem

`URLService` raises `URLNotFoundError`. Routes call the service. If the exception
propagates out of the route, FastAPI returns a 500 Internal Server Error by default
— wrong status code, confusing error message.

### The Solution: `@app.exception_handler`

```python
@app.exception_handler(URLNotFoundError)
async def not_found_handler(request: Request, exc: URLNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})
```

This registers a handler for `URLNotFoundError`. Whenever that exception propagates
out of any route, FastAPI catches it and calls this handler instead of returning 500.

The handler returns a proper JSON 404 response with the error message.

### Why Routes Don't Need Try/Except

Without the handler:

```python
@router.get("/{code}")
async def redirect(code: str, service = Depends(get_service)):
    try:
        record = service.redirect(code)
    except URLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return RedirectResponse(url=str(record.original_url), status_code=302)
```

With the handler:

```python
@router.get("/{code}")
async def redirect(code: str, service = Depends(get_service)):
    record = service.redirect(code)   # if this raises URLNotFoundError,
    return RedirectResponse(...)      # the handler catches it automatically
```

The handler is registered once. It applies to every route in the app. No repeated
try/except blocks. This is the **Don't Repeat Yourself (DRY)** principle applied
to error handling.

---

## 7. HTTP Semantics

### Status Codes Used

| Route | Status | Meaning |
|---|---|---|
| `POST /shorten` success | 201 Created | A new resource was created |
| `POST /shorten` invalid URL | 422 Unprocessable Entity | Input validation failed |
| `GET /{code}` success | 302 Found | Temporary redirect |
| `GET /{code}` unknown | 404 Not Found | Resource doesn't exist |
| `GET /stats/{code}` success | 200 OK | Here's your data |
| `GET /stats/{code}` unknown | 404 Not Found | Resource doesn't exist |

### 201 vs 200 for POST

`200 OK` means "the request succeeded."
`201 Created` means "the request succeeded AND a new resource was created."

`POST /shorten` creates a new URL record. `201` is semantically correct.
Many APIs return `200` for everything — technically wrong but common. Being
correct here costs nothing and signals attention to HTTP standards.

### 302 vs 301 for Redirects

`301 Moved Permanently` — the resource has permanently moved. Browsers cache this.
If the short code ever changes or expires, the browser still redirects to the old
URL from cache. Dangerous for URL shorteners.

`302 Found` — temporary redirect. Browsers don't cache this. Every request hits
your server, which means you can change where a code points, expire codes, and count
clicks accurately. Always use 302 for URL shorteners.

### The `location` Header

A redirect response must include a `location` header with the destination URL:

```
HTTP/1.1 302 Found
Location: https://example.com/some/path
```

`RedirectResponse(url=..., status_code=302)` sets this header automatically.
The test `test_redirect_follows_to_original_url` verifies it directly:

```python
assert response.headers["location"] == "https://example.com/some/path"
```

---

## 8. Route Order

### The Problem

FastAPI matches routes in the order they are registered. Both of these routes
match a path like `/stats/abc`:

```
GET /stats/{code}   → matches with code = "abc"
GET /{code}         → matches with code = "stats/abc"
```

If `/{code}` is registered first, FastAPI matches `/stats/abc` there and passes
`code = "stats/abc"` to the redirect route. Your stats endpoint is unreachable.

### The Rule

**More specific routes must be registered before more general routes.**

```python
# CORRECT — specific before general
@router.get("/stats/{code}")   # registered first
async def get_stats(...): ...

@router.get("/{code}")          # registered second
async def redirect(...): ...
```

This is not unique to FastAPI — all URL routers have this behaviour. Express,
Django, Rails — all match in registration order.

---

## 9. Integration Tests vs Unit Tests

### Phase 4 Tests Were Unit Tests

```python
# Unit test — tests URLService in isolation
def test_shorten_returns_record():
    repo = InMemoryURLRepository()
    service = URLService(repo)
    record = service.shorten("https://example.com")
    assert record.code
```

No HTTP. No FastAPI. Fast. Tests one class.

### Phase 5 Tests Are Integration Tests

```python
# Integration test — tests the full HTTP stack
async def test_shorten_returns_201_with_code(client: AsyncClient):
    response = await client.post("/shorten", json={"url": "https://example.com"})
    assert response.status_code == 201
    assert "code" in response.json()
```

This test exercises:
- `AsyncClient` sends an HTTP request
- FastAPI receives it and runs the route
- The route calls `URLService`
- `URLService` calls `InMemoryURLRepository`
- The response is built and returned
- The test asserts on the HTTP response

More coverage per test. But if it fails, the failure could be in any layer —
harder to pinpoint than a unit test.

### Why Both Are Needed

Unit tests verify business logic is correct.
Integration tests verify the layers connect correctly.

A bug can exist even when all unit tests pass. Example: the route might call
`service.shorten(body.url)` instead of `service.shorten(str(body.url))` — passing
a `HttpUrl` object where a `str` is expected. Unit tests don't catch this because
they never involve routes. Integration tests catch it on the first request.

### `follow_redirects=False`

```python
response = await client.get(f"/{code}", follow_redirects=False)
```

By default, `httpx` follows redirects automatically — a 302 becomes a GET to the
new location, and the final 200 response is returned. You'd never see the 302.

`follow_redirects=False` stops the client at the redirect. You get the actual 302
response with the `location` header. Essential for testing redirect behaviour.

---

## 10. Mistakes Made in This Phase

### Mistake 1 — Wrong import path

```python
# Written in main.py
from app.api.routes import router    # ImportError — router is in urls.py

# Fix
from app.api.routes.urls import router
```

`app/api/routes/` is a package (folder with `__init__.py`). `router` lives inside
`urls.py` within that package. The full module path is `app.api.routes.urls`.

### Mistake 2 — Calling a method that doesn't exist

```python
# Written in redirect route
original_url = service.resolve(code)   # AttributeError — no method called 'resolve'

# Fix
record = service.redirect(code)
```

`URLService` has three methods: `shorten`, `redirect`, `get_stats`. No `resolve`.
Read the service before writing routes that call it.

### Mistake 3 — Returning the domain object where the service returns a record

```python
# Written
return RedirectResponse(url=record, status_code=302)
# record is a URLRecord object — not a URL string
# FastAPI serialises it as its string representation: "URLRecord(id=1, code='1'...)"

# Fix
return RedirectResponse(url=str(record.original_url), status_code=302)
```

`service.redirect()` returns a `URLRecord`. `RedirectResponse(url=...)` needs a URL
string. You must extract `record.original_url` and convert it to `str`.

### Mistake 4 — Dead null check after service call

```python
# Written
record = service.redirect(code)
if record is None:             # this never executes — service raises, not returns None
    raise HTTPException(...)   # dead code

# Fix — delete the null check entirely
record = service.redirect(code)
return RedirectResponse(url=str(record.original_url), status_code=302)
```

`service.redirect()` raises `URLNotFoundError` when the code doesn't exist.
It never returns `None`. The null check is dead code. More importantly, the
`HTTPException` had `status_code=302` — a redirect status code for an error response.
That would have confused every HTTP client.

### Mistake 5 — Variable name inconsistency

```python
# Written
original_url = service.redirect(code)   # named original_url
...
url=str(record.original_url)            # used name 'record' — NameError

# Fix — consistent naming
record = service.redirect(code)
...
url=str(record.original_url)
```

Python variables are case-sensitive and scope-local. If you name it `original_url`
on one line, you can't access it as `record` on another. Read your own code before
running it.

---

## 11. Code Reference — `app/api/schemas.py`

```python
from __future__ import annotations
from pydantic import BaseModel, HttpUrl
```

**`BaseModel`** — base class for all Pydantic models. Provides `__init__` with
type validation, `.model_dump()` for serialization, and `.model_validate()` for
parsing. FastAPI uses `BaseModel` subclasses as request/response schemas.

**`HttpUrl`** — a Pydantic type that validates HTTP/HTTPS URLs. Rejects anything
that isn't a valid URL. Also normalises URLs (adds trailing slash to bare domains).

```python
class ShortenRequest(BaseModel):
    url: HttpUrl
```

Used as a request body schema. FastAPI reads the JSON body, validates `url` is a
real URL, and passes the validated `ShortenRequest` object to the route.

```python
class ShortenResponse(BaseModel):
    code: str
    short_url: str
    original_url: str
```

Used as a response schema. FastAPI validates the route's return value against this
and serialises it to JSON. `short_url` is built in the route — it doesn't exist on
`URLRecord` and must be constructed from `settings.base_url + "/" + record.code`.

```python
class StatsResponse(BaseModel):
    code: str
    original_url: str
    click_count: int
    created_at: str
```

`created_at` is a `str` not `datetime` because JSON has no native datetime type.
The route converts `record.created_at.isoformat()` to produce an ISO 8601 string.

---

## 12. Code Reference — `app/api/dependencies.py`

```python
from __future__ import annotations
from fastapi import Request
from app.domain.services import URLService


def get_service(request: Request) -> URLService:
    return request.app.state.service
```

**`get_service`** — a FastAPI dependency function. Called by `Depends(get_service)`
in route signatures. FastAPI injects the current `Request` automatically.

**`request.app`** — the FastAPI application instance. Same object created by
`app = FastAPI(...)` in `main.py`.

**`request.app.state`** — the namespace set up during `lifespan`. Contains
`service` — the `URLService` instance initialized at startup.

**Why a separate file?** Keeps dependency functions isolated from routes. As the
app grows (Phases 6, 7), more dependencies are added here — database sessions,
Redis clients, rate limiters. Centralised in one file, not scattered across routes.

---

## 13. Code Reference — `app/api/routes/urls.py`

```python
from fastapi import APIRouter, Depends, status
from fastapi.responses import RedirectResponse
from app.api.dependencies import get_service
from app.api.schemas import ShortenRequest, ShortenResponse, StatsResponse
from app.domain.services import URLService
from app.config import settings

router = APIRouter()
```

**`APIRouter()`** — a route collector. Routes defined on `router` are registered
with the FastAPI app when `app.include_router(router)` is called in `main.py`.

---

```python
@router.post(
    "/shorten",
    response_model=ShortenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def shorten_url(
    body: ShortenRequest,
    service: URLService = Depends(get_service),
) -> ShortenResponse:
    record = service.shorten(str(body.url))
    return ShortenResponse(
        code=record.code,
        short_url=f"{settings.base_url}/{record.code}",
        original_url=str(record.original_url),
    )
```

**`str(body.url)`** — `body.url` is an `HttpUrl` object. `URLService.shorten`
expects a plain `str`. Wrap it in `str()` to convert.

**`str(record.original_url)`** — `URLRecord.original_url` is already a `str`
in Phase 5. This explicit cast guards against Phase 6 where it might be an
`HttpUrl` after being loaded from Pydantic-validated input.

**`f"{settings.base_url}/{record.code}"`** — builds the full short URL from config.
`settings.base_url` is `"http://localhost:8000"` in development. In production, it
would be `"https://short.yourdomain.com"`. Reading from config means you change
the domain in one place, not in every route.

---

```python
@router.get("/stats/{code}", response_model=StatsResponse)
async def get_stats(
    code: str,
    service: URLService = Depends(get_service),
) -> StatsResponse:
    record = service.get_stats(code)
    return StatsResponse(
        code=record.code,
        original_url=str(record.original_url),
        click_count=record.click_count,
        created_at=record.created_at.isoformat(),
    )
```

**`record.created_at.isoformat()`** — `datetime.isoformat()` produces a string
like `"2026-06-15T12:34:56.789012+00:00"`. Timezone-aware because `created_at`
was stored with `timezone.utc`.

**No null check needed** — `service.get_stats()` raises `URLNotFoundError` on
unknown codes. The exception handler in `main.py` catches it and returns 404.

---

```python
@router.get("/{code}")
async def redirect(
    code: str,
    service: URLService = Depends(get_service),
) -> RedirectResponse:
    record = service.redirect(code)
    return RedirectResponse(
        url=str(record.original_url),
        status_code=status.HTTP_302_FOUND,
    )
```

**`str(record.original_url)`** — same reason as above. `RedirectResponse(url=...)`
requires a string. Explicit cast for safety.

**`status.HTTP_302_FOUND`** — `302` as a named constant. Using named constants
instead of bare integers makes code self-documenting. `status.HTTP_302_FOUND` is
immediately clear. `302` requires you to remember what it means.

---

## 14. Code Reference — `app/main.py` (updated)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.config import settings
from app.domain.memory import InMemoryURLRepository
from app.domain.services import URLService
from app.exceptions import URLNotFoundError


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.service = URLService(repo=InMemoryURLRepository())
    yield
    # Phase 6: drain connection pool, close Redis here


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
```

**`app.state.service = URLService(repo=InMemoryURLRepository())`** — creates one
`URLService` instance at startup. All routes share this instance via `Depends(get_service)`.
In Phase 6, `InMemoryURLRepository` is replaced with `PostgresURLRepository`.

**`@app.exception_handler(URLNotFoundError)`** — registers a global handler.
Any `URLNotFoundError` that propagates out of any route is caught here. The handler
returns a JSON 404 response. Keeps all routes clean — no try/except anywhere.

**`app.include_router(router)`** — registers all routes defined in `urls.py` with
the FastAPI app. The import is at the bottom intentionally — `app` must be created
before the router is imported, because importing `urls.py` also imports `dependencies.py`
which imports from `app.domain.services` — all of which must exist first.

---

## 15. Code Reference — `tests/conftest.py` (updated)

```python
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
```

**Why `app.state.service` is reset in the fixture:**

`app` is a module-level object — it's created once when `main.py` is imported.
`app.state.service` persists between tests if not reset. Test A shortens a URL.
Test B runs and the service still has that URL in its repo. Tests interfere with
each other — order-dependent failures.

Resetting `app.state.service = URLService(repo=InMemoryURLRepository())` at the
start of each fixture gives every test a fresh service with an empty repo. Tests
are now independent and can run in any order.

---

## 16. Code Reference — `tests/test_routes.py`

### `test_shorten_returns_201_with_code`

```python
async def test_shorten_returns_201_with_code(client: AsyncClient):
    response = await client.post("/shorten", json={"url": "https://example.com"})
    assert response.status_code == 201
    data = response.json()
    assert "code" in data
    assert data["code"] != ""
```

Tests the happy path for the shorten endpoint. Verifies status code is 201 (not 200),
response body is JSON, and `code` is present and non-empty.

### `test_shorten_invalid_url_returns_422`

```python
async def test_shorten_invalid_url_returns_422(client: AsyncClient):
    response = await client.post("/shorten", json={"url": "not-a-url"})
    assert response.status_code == 422
```

Tests that Pydantic's `HttpUrl` validation fires. `"not-a-url"` has no scheme
(no `http://` or `https://`). FastAPI returns 422 automatically — the route
function never runs.

### `test_redirect_known_code_returns_302`

```python
async def test_redirect_known_code_returns_302(client: AsyncClient):
    create = await client.post("/shorten", json={"url": "https://example.com"})
    code = create.json()["code"]
    response = await client.get(f"/{code}", follow_redirects=False)
    assert response.status_code == 302
```

**Two-step test:** first creates a short URL, then uses the code to test the redirect.
`follow_redirects=False` stops at the 302 — without this, httpx would follow the
redirect and return the final response from `example.com`.

### `test_redirect_follows_to_original_url`

```python
async def test_redirect_follows_to_original_url(client: AsyncClient):
    original = "https://example.com/some/path"
    create = await client.post("/shorten", json={"url": original})
    code = create.json()["code"]
    response = await client.get(f"/{code}", follow_redirects=False)
    assert response.headers["location"] == original
```

Verifies the `location` header contains the exact original URL. Uses a path
`/some/path` to avoid pydantic's trailing slash normalisation on bare domains.
The `location` header is what browsers and HTTP clients use to follow the redirect.

### `test_stats_click_count_increases_after_redirect`

```python
async def test_stats_click_count_increases_after_redirect(client: AsyncClient):
    create = await client.post("/shorten", json={"url": "https://example.com"})
    code = create.json()["code"]

    before = await client.get(f"/stats/{code}")
    before_count = before.json()["click_count"]

    await client.get(f"/{code}", follow_redirects=False)

    after = await client.get(f"/stats/{code}")
    after_count = after.json()["click_count"]

    assert after_count == before_count + 1
```

The most complete integration test. Verifies the full click tracking flow:
1. Shorten a URL
2. Read stats — baseline click count
3. Trigger a redirect
4. Read stats again — count must be exactly 1 higher

This test only passes if the redirect route correctly calls
`repo.increment_clicks(code)` through the service. The repository bypass bug
from Phase 4 would have caused this test to fail — verifying that the fix
(`self._repo.increment_clicks(code)`) was correct.

---

## 17. What Phase 5 Does NOT Have Yet

- **No real database** — still using `InMemoryURLRepository`. All data is lost
  on process restart. Phase 6 adds PostgreSQL.
- **No Redis** — no distributed caching. Every redirect hits the in-memory repo.
  Phase 7 adds Redis.
- **No rate limiting** — `POST /shorten` and `GET /{code}` have no request limits.
  Rate limiter was built in the session exercises and gets wired in Phase 7.
- **No Docker** — app can only run locally. Phase 8 adds Dockerfile and
  docker-compose.
- **No deployed URL** — Phase 8 also handles Fly.io deployment.
- **URL validation beyond format** — `HttpUrl` validates format but not reachability.
  A URL to `https://totallynotasite.fake` passes validation.

---

## 18. Phase 6 Preview

Phase 6 replaces `InMemoryURLRepository` with `PostgresURLRepository` — a real
database implementation backed by PostgreSQL.

**New dependencies added:**
```
sqlalchemy[asyncio]
asyncpg
alembic
```

**New files:**
```
app/infrastructure/database.py     → async SQLAlchemy engine + session factory
app/infrastructure/models.py       → SQLAlchemy ORM table definition
app/infrastructure/repositories/
    postgres.py                    → PostgresURLRepository (implements URLRepository)
alembic/                           → database migration files
alembic.ini                        → alembic config
```

**What changes in `main.py`:**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_async_engine(settings.database_url)
    async_session = async_sessionmaker(engine)
    app.state.service = URLService(
        repo=PostgresURLRepository(async_session)
    )
    yield
    await engine.dispose()   # clean shutdown
```

**The key insight:** `URLService` doesn't change. `urls.py` routes don't change.
`schemas.py` doesn't change. Only the repository implementation swaps. That's the
Repository Pattern working exactly as designed.

---

*Phase 5 complete. 50 tests passing across all five phases.*
*The application is now usable end-to-end with in-memory storage.*
*Phase 6 makes it production-ready with a real database.*
