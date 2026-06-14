# Phase 4 — Service Layer
### URL Shortener Build Log

> This document explains everything built in Phase 4 — what a service layer is,
> why it exists, how it connects the domain models and repository, what dependency
> injection means at this level, and every mistake made and why it matters.
> Read this before touching Phase 5.

---

## Table of Contents

1. [What Phase 4 Builds](#1-what-phase-4-builds)
2. [The Service Layer — What It Is and Why It Exists](#2-the-service-layer)
3. [Dependency Injection — The Core Principle](#3-dependency-injection)
4. [The Three Operations](#4-the-three-operations)
5. [Critical Mistake — Bypassing the Repository](#5-critical-mistake-bypassing-the-repository)
6. [Critical Mistake — Wildcard Imports](#6-critical-mistake-wildcard-imports)
7. [How the Layers Connect Now](#7-how-the-layers-connect-now)
8. [Testing the Service Layer](#8-testing-the-service-layer)
9. [The Final Implementation](#9-the-final-implementation)
10. [The Final Tests](#10-the-final-tests)
11. [What Phase 4 Does NOT Have Yet](#11-what-phase-4-does-not-have-yet)
12. [Phase 5 Preview](#12-phase-5-preview)

---

## 1. What Phase 4 Builds

One file: `app/domain/services.py`
One test file: `tests/test_services.py`
9 passing tests.

Zero FastAPI. Zero database. Zero HTTP. Zero configuration.

`URLService` is the orchestrator — it takes the Base62 algorithm from Phase 2
and the repository from Phase 3 and combines them into three operations: shorten
a URL, redirect using a code, and fetch stats. Every business rule in the application
lives in this class.

---

## 2. The Service Layer

### Where It Sits

```
[ API Layer ]      app/api/routes/      ← receives HTTP, returns HTTP
      ↓
[ Service Layer ]  app/domain/services.py  ← business logic lives here
      ↓
[ Repository ]     app/domain/repositories.py  ← storage abstraction
      ↓
[ Database ]       app/infrastructure/  ← actual SQL queries
```

The service layer is the middle tier. It owns the business logic — the rules about
what happens when a URL is shortened, what happens when a redirect is requested,
what constitutes a valid operation. It knows nothing about HTTP status codes or
database columns.

### What "Business Logic" Means

Business logic is every decision your application makes that isn't about HTTP or
databases:

- When shortening a URL: get a unique ID, encode it, build a record, persist it
- When redirecting: look up the code, if it doesn't exist raise an error, count the click
- When fetching stats: look up the code, if it doesn't exist raise an error, return it

None of these decisions are about HTTP. They're about the domain — what a URL
shortener does. That's why they live in `app/domain/`.

### Why Not Put Logic in Routes?

Without a service layer, routes look like this:

```python
@app.post("/shorten")
async def shorten(body: ShortenRequest, db=Depends(get_db)):
    # business logic
    next_id = await db.execute("SELECT nextval('urls_id_seq')")
    code = base62.encode(next_id)

    # storage logic
    await db.execute(
        "INSERT INTO urls (id, code, original_url) VALUES ($1, $2, $3)",
        next_id, code, body.url
    )
    await db.commit()

    # response building
    return {"code": code, "short_url": f"https://myapp.com/{code}"}
```

**Everything is tangled in one function.** To test the "get ID → encode → save"
logic you must set up a real database and make an HTTP request. To add a CLI
that also shortens URLs, you copy and paste this logic. To change the ID encoding
algorithm, you hunt through route files.

With a service layer:

```python
@app.post("/shorten")
async def shorten(body: ShortenRequest, service=Depends(get_service)):
    record = service.shorten(body.url)     # one line, zero logic in the route
    return ShortenResponse(code=record.code, short_url=...)
```

The route handles HTTP concerns only. The service handles business logic only.
Each is testable independently.

---

## 3. Dependency Injection

### What It Is

Dependency Injection (DI) means: **a class receives its dependencies from outside
rather than creating them internally.**

```python
# WITHOUT DI — class creates its own dependency
class URLService:
    def __init__(self) -> None:
        self._repo = InMemoryURLRepository()   # hardcoded — cannot swap
```

```python
# WITH DI — dependency is injected from outside
class URLService:
    def __init__(self, repo: URLRepository) -> None:
        self._repo = repo   # injected — can be anything that implements the interface
```

**The difference in usage:**

```python
# Tests — inject a fast, lightweight fake
service = URLService(repo=InMemoryURLRepository())

# Production — inject the real database implementation
service = URLService(repo=PostgresURLRepository(db_session))

# Future — inject a Redis-backed implementation
service = URLService(repo=RedisURLRepository(redis_client))
```

Same `URLService` class. Same tests. Same business logic. Different storage backend.
Zero changes to the service when you swap the backend.

### The Analogy

> A chef doesn't grow their own vegetables. They receive ingredients from a supplier.
> The chef's job — cooking techniques, recipes, presentation — stays the same
> regardless of whether the supplier is a local farm, a wholesaler, or a greenhouse.
>
> `URLService` is the chef. `URLRepository` is the supplier interface.
> `InMemoryURLRepository` and `PostgresURLRepository` are different suppliers.
> The cooking doesn't change when the supplier changes.

### Why Type as the Interface

```python
def __init__(self, repo: URLRepository) -> None:
```

The type hint says `URLRepository` (the abstract interface), not
`InMemoryURLRepository` (a concrete class). This is deliberate.

If you type it as `InMemoryURLRepository`, you can accidentally call methods
that only exist on the in-memory version — breaking when the Postgres version is
injected. Typing as the interface means you can only call methods defined on the
contract. The type checker enforces this.

---

## 4. The Three Operations

### `shorten(original_url: str) -> URLRecord`

```python
def shorten(self, original_url: str) -> URLRecord:
    record_id = self._repo.next_id()       # step 1: get unique integer ID
    code = encode(record_id)               # step 2: encode to base62 string
    record = URLRecord(                    # step 3: build the domain model
        id=record_id,
        original_url=original_url,
        code=code,
    )
    return self._repo.save(record)         # step 4: persist and return
```

**Step 1 — `next_id()`:**
Gets the next unique integer. In-memory: increments a counter. In Postgres: the
`SERIAL` column returns the auto-assigned ID after INSERT. Either way, the service
gets a unique integer without knowing how it was generated.

**Step 2 — `encode(record_id)`:**
Converts the integer to a base62 string. `encode(1)` → `"1"`. `encode(62)` → `"10"`.
`encode(1_000_000)` → `"4c92"`. This is the actual short code.

**Step 3 — Build `URLRecord`:**
The domain model is created with the ID, code, and original URL. `created_at`
defaults to `datetime.now(tz=timezone.utc)` and `click_count` defaults to 0 —
both handled by `@dataclass` default factories.

**Step 4 — `save()` and return its result:**
`self._repo.save(record)` persists the record and returns it. The service returns
the saved record — not the input record. This matters in Phase 6: the Postgres
implementation assigns the ID during the INSERT and returns a record with that
ID populated. The service always works with the DB-assigned record.

---

### `redirect(code: str) -> URLRecord`

```python
def redirect(self, code: str) -> URLRecord:
    record = self._repo.get_by_code(code)
    if record is None:
        raise URLNotFoundError(code)
    self._repo.increment_clicks(code)      # correct: goes through repository
    return record
```

**`get_by_code(code)`** — look up the record. Returns `None` if it doesn't exist.

**`if record is None: raise URLNotFoundError(code)`** — the business rule:
unknown codes are errors. The service raises a domain exception. The API layer
catches it and converts to HTTP 404. Two different concerns, two different layers.

**`self._repo.increment_clicks(code)`** — the correct way to update state.
See Section 5 for the critical mistake that bypasses this.

---

### `get_stats(code: str) -> URLRecord`

```python
def get_stats(self, code: str) -> URLRecord:
    record = self._repo.get_by_code(code)
    if record is None:
        raise URLNotFoundError(code)
    return record
```

Identical to `redirect` except no click increment. Stats are **read-only**.
Calling `get_stats` must not change any state. This is the **Command-Query
Separation** principle: operations that read and operations that write are separate.
`redirect` writes (increments clicks). `get_stats` reads only.

`test_get_stats_does_not_increment` explicitly verifies this:

```python
service.get_stats(record.code)
service.get_stats(record.code)
assert record.click_count == 0   # two stats calls, zero click increments
```

---

## 5. Critical Mistake — Bypassing the Repository

### What Was Written

```python
def redirect(self, code: str) -> URLRecord:
    record = self._repo.get_by_code(code)
    if record is None:
        raise URLNotFoundError(code)
    record.click_count += 1       # WRONG — directly mutating the object
    return record
```

### Why Tests Still Passed

`InMemoryURLRepository` stores the actual Python object reference in its dict:

```python
# Inside InMemoryURLRepository
self._store["abc123"] = record   # stores the reference, not a copy
```

When `get_by_code("abc123")` is called, it returns the same object that's in `_store`.
When you mutate `record.click_count += 1`, you're changing the object that
`_store` also points to. So `repo.get_by_code("abc123").click_count` reflects the
change.

```
service.redirect("abc123")
  → record = repo.get_by_code("abc123")   # returns the object at _store["abc123"]
  → record.click_count += 1               # mutates the object _store["abc123"] points to
  → repo.get_by_code("abc123").click_count  # 1 — same object
```

The test sees the correct value. Tests pass. Bug is invisible.

### Why It Fails in Production

With PostgreSQL, `get_by_code` does something like:

```python
async def get_by_code(self, code: str) -> URLRecord | None:
    row = await db.execute("SELECT * FROM urls WHERE code = $1", code)
    if row is None:
        return None
    return URLRecord(   # creates a NEW Python object from the DB row
        id=row["id"],
        code=row["code"],
        original_url=row["original_url"],
        click_count=row["click_count"],
    )
```

Every call to `get_by_code` builds a **new `URLRecord` object** from the database
row. Mutating that object changes only the in-memory Python object:

```
record = repo.get_by_code("abc123")
# record is a NEW Python object — not connected to the database
record.click_count += 1
# This changes the Python object in memory
# The database row is untouched — still shows 0
```

Every redirect increments the in-memory object. The database never gets updated.
No error is raised. No exception. The app appears to work. But every `GET /stats`
returns `click_count: 0` because it reads from the database.

**This is one of the most common bugs in backend development.** It's invisible
in unit tests because in-memory objects work differently from database-loaded objects.
It only manifests in integration tests or production.

### The Correct Fix

```python
self._repo.increment_clicks(code)
```

This calls the repository method, which in the Postgres implementation issues:

```sql
UPDATE urls SET click_count = click_count + 1 WHERE code = $1
```

The database is updated. The source of truth is updated. Every subsequent
`get_by_code` reads the correct count from the database.

### The Rule This Teaches

**Never mutate a domain object's state directly when that state must be persisted.**
Always go through the repository. The repository is the single path to the database.
Bypassing it means your in-memory state diverges from your persistent state — silently.

---

## 6. Critical Mistake — Wildcard Imports

### What Was Written

```python
from app.exceptions import *
```

### Why This Is Wrong

`import *` imports every name from the module into the current namespace. You
cannot tell by reading `services.py` what names are available — you must open
`exceptions.py` and read it.

**Problems:**

**1. Invisible dependencies.** If someone adds `class Foo` to `exceptions.py`,
it silently appears in `services.py`'s namespace. You didn't ask for it. You
didn't know it was there.

**2. Name collisions.** If `exceptions.py` and another import both define a
name `Error`, whichever is imported last wins. Silently. No warning.

**3. Breaks tooling.** `mypy`, `ruff`, `pylint`, IDE autocompletion — all work
by statically analyzing imports. Wildcard imports are opaque. Tools can't know
what names exist.

**4. Makes code unreadable.** A future developer reads `raise URLNotFoundError(code)`
and searches `services.py` for where `URLNotFoundError` is imported. It's not there
explicitly — it came from `import *`. They must hunt.

### The Fix

```python
from app.exceptions import URLNotFoundError
```

Import exactly what you use. If you need three exceptions:

```python
from app.exceptions import URLNotFoundError, URLExpiredError, InvalidURLError
```

Explicit is always better than implicit in Python. This is **The Zen of Python**
item 2: "Explicit is better than implicit."

### The Unused Import

```python
# What was written
from app.algorithms.base62 import encode, decode

# decode is never used in services.py — remove it
from app.algorithms.base62 import encode
```

Unused imports add noise. They imply that `decode` is used somewhere in this file
when it isn't. Tools like `ruff` flag these automatically. In a production repo with
CI, unused imports fail the lint check and block the PR merge.

---

## 7. How the Layers Connect Now

After Phase 4, three layers are complete and connected:

```
Base62 Algorithm (Phase 2)
    encode(id) → code
    decode(code) → id
         ↓
URLRepository Interface (Phase 3)
    save / get_by_code / increment_clicks / next_id
         ↓
    InMemoryURLRepository (Phase 3)
    (PostgresURLRepository — Phase 6)
         ↓
URLService (Phase 4)
    shorten(url) → URLRecord
    redirect(code) → URLRecord
    get_stats(code) → URLRecord
```

The service depends on the algorithm and the repository. The algorithm depends on
nothing. The repository interface depends on the domain model. Everything flows
downward. No circular dependencies.

### Request Flow (So Far)

```
Client wants to shorten "https://example.com"

1. service.shorten("https://example.com")
2.   → repo.next_id()             returns 1
3.   → encode(1)                  returns "1"
4.   → URLRecord(id=1, code="1", original_url="https://example.com")
5.   → repo.save(record)          stores and returns record
6. returns URLRecord

Client wants to redirect using code "1"

1. service.redirect("1")
2.   → repo.get_by_code("1")      returns the URLRecord
3.   → repo.increment_clicks("1") updates click_count
4. returns URLRecord (caller uses record.original_url to redirect)

Client wants stats for code "1"

1. service.get_stats("1")
2.   → repo.get_by_code("1")      returns the URLRecord
3. returns URLRecord (no mutation)
```

---

## 8. Testing the Service Layer

### The Testing Philosophy for Services

Service tests are **unit tests** — they test one unit of logic in isolation.
The repository is injected as `InMemoryURLRepository` — no database, no I/O.
The tests run in milliseconds. Each test creates a fresh service and repository.

This proves the business logic is correct independent of storage. When Phase 6
adds PostgreSQL, a separate set of **integration tests** will verify the Postgres
implementation. The service tests here remain unchanged.

### Key Test: `test_shorten_code_is_valid_base62`

```python
def test_shorten_code_is_valid_base62() -> None:
    repo: URLRepository = InMemoryURLRepository()
    service = URLService(repo)

    record = service.shorten("https://example.com")

    assert decode(record.code) == record.id
```

This test proves the fundamental contract: the code is the base62 encoding of the ID.
`decode(encode(id)) == id` — the roundtrip property. If the encoding step breaks,
this test catches it. It also proves the code and ID are consistent with each other.

### Key Test: `test_shorten_multiple_unique_codes`

```python
def test_shorten_multiple_unique_codes() -> None:
    repo: URLRepository = InMemoryURLRepository()
    service = URLService(repo)

    record1 = service.shorten("https://a.com")
    record2 = service.shorten("https://b.com")
    record3 = service.shorten("https://c.com")

    codes = {record1.code, record2.code, record3.code}
    assert len(codes) == 3
```

Converting to a `set` and checking its length is the idiomatic Python way to assert
uniqueness. A set only stores unique values. If any two codes were identical,
`len(codes)` would be less than 3.

This test proves the `next_id() → encode()` pipeline produces unique codes.

### Key Test: `test_redirect_returns_record` — `is` vs `==`

```python
def test_redirect_returns_record() -> None:
    ...
    assert record is created
```

`is` checks **object identity** — are these two variables pointing to the exact
same object in memory? `==` checks **value equality** — do these objects have
the same field values?

Using `is` here is intentional. The service should return the exact same object
that was stored — not a copy with equal values. With in-memory storage, this
should always be true. If it returned a copy, `is` would catch it.

In Phase 6 with Postgres, this test may need to change to `==` because the database
returns a new object with the same values — not the same Python object in memory.

### Key Test: `test_redirect_increments_clicks`

```python
def test_redirect_increments_clicks() -> None:
    ...
    assert record.click_count == 0
    service.redirect(record.code)
    assert record.click_count == 1
    service.redirect(record.code)
    assert record.click_count == 2
```

Tests the counter after each redirect individually — not just a final assertion.
This proves the count increments by exactly 1 per redirect, not by more or less.

---

## 9. The Final Implementation

```python
# app/domain/services.py

from __future__ import annotations
from app.algorithms.base62 import encode
from app.domain.models import URLRecord
from app.domain.repositories import URLRepository
from app.exceptions import URLNotFoundError


class URLService:
    """
    Orchestrates all URL shortening business operations.

    Depends on URLRepository (injected) — never on a concrete implementation.
    Raises domain exceptions — never HTTP exceptions.
    """

    def __init__(self, repo: URLRepository) -> None:
        self._repo = repo

    def shorten(self, original_url: str) -> URLRecord:
        """
        Create a new short URL mapping.

        Gets the next unique ID from the repository, encodes it to base62,
        builds a URLRecord, persists it, and returns the saved record.
        """
        record_id = self._repo.next_id()
        code = encode(record_id)
        record = URLRecord(
            id=record_id,
            original_url=original_url,
            code=code,
        )
        return self._repo.save(record)

    def redirect(self, code: str) -> URLRecord:
        """
        Resolve a short code to its original URL.

        Records a click via the repository (not by mutating the object directly).
        Raises URLNotFoundError if the code does not exist.
        """
        record = self._repo.get_by_code(code)
        if record is None:
            raise URLNotFoundError(code)
        self._repo.increment_clicks(code)   # correct path — through repository
        return record

    def get_stats(self, code: str) -> URLRecord:
        """
        Return analytics for a short code without recording a click.

        Read-only. Does not mutate any state.
        Raises URLNotFoundError if the code does not exist.
        """
        record = self._repo.get_by_code(code)
        if record is None:
            raise URLNotFoundError(code)
        return record
```

---

## 10. The Final Tests

```python
# tests/test_services.py

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
    service.get_stats(record.code)

    assert record.click_count == 0
```

---

## 11. What Phase 4 Does NOT Have Yet

- **No HTTP layer** — `URLService` raises `URLNotFoundError`. Nothing converts
  that to a `404` response yet. That translation happens in Phase 5 routes.
- **No FastAPI integration** — the service is not attached to `app.state` yet.
  Routes get it via `Depends()` in Phase 5.
- **No URL validation** — `shorten("not a url")` currently accepts anything.
  Pydantic validates URLs at the HTTP layer in Phase 5.
- **No async** — the service is synchronous. Phase 6 converts everything to
  `async def` when real database I/O is introduced.
- **No expiry** — `URLExpiredError` exists in `exceptions.py` but is never raised.
  TTL logic is a future addition.

---

## 12. Phase 5 Preview

Phase 5 builds the **API routes** — the HTTP layer that connects `URLService`
to the outside world.

Three routes:

```
POST /shorten          → service.shorten(url) → 201 Created
GET  /{code}           → service.redirect(code) → 302 Redirect
GET  /stats/{code}     → service.get_stats(code) → 200 OK
```

**Pydantic request and response models:**

```python
class ShortenRequest(BaseModel):
    url: HttpUrl    # validates it's a real HTTP(S) URL

class ShortenResponse(BaseModel):
    code: str
    short_url: str
    original_url: str

class StatsResponse(BaseModel):
    code: str
    original_url: str
    click_count: int
    created_at: str
```

**Exception handlers** — translate domain exceptions to HTTP:

```python
@app.exception_handler(URLNotFoundError)
async def not_found_handler(request, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})
```

**`URLService` on `app.state`** — initialized in `lifespan`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.service = URLService(repo=InMemoryURLRepository())
    yield
```

**Rate limiting** — `POST /shorten` is strictly limited (10/min), `GET /{code}`
is loosely limited (60/min).

Phase 5 tests are **integration tests** — they test the full HTTP stack using
`AsyncClient` and `ASGITransport`. A `POST /shorten` request goes through Pydantic
validation, the route handler, `URLService`, `InMemoryURLRepository`, and back.

---

*Phase 4 complete. 42 tests passing across all four phases.*
*Business logic is done. The next phase exposes it to the world via HTTP.*
