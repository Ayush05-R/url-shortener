# Phase 3 — Domain Models + Repository Pattern
### URL Shortener Build Log

> This document explains everything built in Phase 3 — what a domain model is,
> why the Repository Pattern exists, how abstract base classes enforce contracts,
> and every design decision made. Read this before touching Phase 4.

---

## Table of Contents

1. [What Phase 3 Builds](#1-what-phase-3-builds)
2. [The Domain Layer — What It Is and Why It Exists](#2-the-domain-layer)
3. [Domain Models — `URLRecord`](#3-domain-models)
4. [The Repository Pattern — From First Principles](#4-the-repository-pattern)
5. [Abstract Base Classes — How Python Enforces Contracts](#5-abstract-base-classes)
6. [The Repository Interface — `URLRepository`](#6-the-repository-interface)
7. [In-Memory Implementation — `InMemoryURLRepository`](#7-in-memory-implementation)
8. [Testing the Repository Pattern](#8-testing-the-repository-pattern)
9. [Design Decisions Explained](#9-design-decisions-explained)
10. [The Final Implementation](#10-the-final-implementation)
11. [The Final Tests](#11-the-final-tests)
12. [What Phase 3 Does NOT Have Yet](#12-what-phase-3-does-not-have-yet)
13. [Phase 4 Preview](#13-phase-4-preview)

---

## 1. What Phase 3 Builds

Three files in `app/domain/`:

```
app/domain/
├── models.py        → URLRecord dataclass — the data shape
├── repositories.py  → URLRepository ABC — the interface/contract
└── memory.py        → InMemoryURLRepository — the concrete implementation
```

One test file: `tests/test_repository.py`
6 passing tests.

Zero FastAPI. Zero database. Zero HTTP. Pure Python business logic.

This phase introduces the two most important architectural patterns in backend
development: the **Domain Model** and the **Repository Pattern**. Every serious
backend application uses both.

---

## 2. The Domain Layer

### What "Domain" Means

The domain is the **core business logic** of your application — the rules, data
shapes, and operations that define what your app actually does, independent of
how it is delivered (HTTP, CLI, or otherwise) and how data is stored (Postgres,
Redis, files, or otherwise).

For a URL shortener, the domain contains:
- What a shortened URL looks like (`URLRecord`)
- What operations exist (save, retrieve, count clicks)
- What rules apply (codes must be unique, click counts only go up)

### The Separation of Concerns

```
app/api/           ← HTTP concerns: receive requests, validate input, return responses
app/domain/        ← Business logic: rules, data shapes, operations
app/infrastructure/← Storage concerns: SQL queries, Redis commands, file I/O
app/algorithms/    ← Pure computation: Base62, Bloom filter, LRU
```

Each layer has one responsibility. Each layer talks only to the one below it.
Routes talk to domain. Domain talks to repositories. Repositories talk to databases.

**Routes never touch the database directly. Ever.**

### Why This Matters

Without separation, a route looks like this:

```python
@app.post("/shorten")
async def shorten(body: ShortenRequest, db: AsyncSession = Depends(get_db)):
    # HTTP validation
    if not body.url.startswith("http"):
        raise HTTPException(...)

    # Business logic
    code = base62.encode(get_next_id())

    # SQL query — directly in the route
    await db.execute(
        "INSERT INTO urls (code, original_url) VALUES ($1, $2)",
        code, body.url
    )
    await db.commit()

    # Response building
    return {"short_url": f"https://myapp.com/{code}"}
```

Everything is tangled in one function. To test the business logic (code generation),
you must run a real database. To change the database (Postgres → MongoDB), you
rewrite routes. To add a CLI interface, you duplicate all this logic.

With separation, the route does only one job. The domain does only one job.
They connect through clean interfaces.

---

## 3. Domain Models

### What a Domain Model Is

A domain model is a **data structure that represents a core concept in your
application**. It carries data and nothing else — no database columns, no HTTP
response formatting, no framework dependencies.

`URLRecord` represents one stored URL mapping. It knows:
- Its unique integer ID
- Its short code
- The original URL it maps to
- When it was created
- How many times it has been clicked

It does NOT know:
- Which database it came from
- What HTTP status code to return
- How to serialize itself to JSON

### Python `@dataclass`

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class URLRecord:
    id: int
    code: str
    original_url: str
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    click_count: int = 0
```

`@dataclass` is a decorator that auto-generates boilerplate based on the class
attributes you declare. It generates:

| Generated method | What it does |
|---|---|
| `__init__` | Constructor that accepts all declared attributes as arguments |
| `__repr__` | String representation: `URLRecord(id=1, code='abc', ...)` |
| `__eq__` | Equality comparison: two `URLRecord` objects are equal if all fields match |

Without `@dataclass`, you write this manually:

```python
class URLRecord:
    def __init__(self, id: int, code: str, original_url: str, ...):
        self.id = id
        self.code = code
        self.original_url = original_url
        ...

    def __repr__(self):
        return f"URLRecord(id={self.id}, code={self.code!r}, ...)"

    def __eq__(self, other):
        if not isinstance(other, URLRecord):
            return NotImplemented
        return self.id == other.id and self.code == other.code and ...
```

`@dataclass` eliminates all of this. Use it for every data container.

### `field(default_factory=...)`

Some attributes need a **dynamic default** — a value computed at instantiation
time, not at class definition time.

```python
# WRONG — defined once when the class is parsed
created_at: datetime = datetime.now(tz=timezone.utc)
# Every URLRecord gets the same timestamp — the time the module was imported.

# CORRECT — computed fresh for each new instance
created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
# Each URLRecord gets the timestamp of when it was created.
```

`default_factory` accepts a callable (a function with no arguments). It calls that
function every time a new instance is created without providing `created_at`.

The `lambda: datetime.now(tz=timezone.utc)` is just a zero-argument function that
returns the current time when called.

### `datetime.now(tz=timezone.utc)` — Not `datetime.utcnow()`

```python
# DEPRECATED — never use this
datetime.utcnow()
# Returns a "naive" datetime — no timezone info attached.
# Python doesn't know this is UTC. Arithmetic with other timezones is broken.

# CORRECT
datetime.now(tz=timezone.utc)
# Returns a "aware" datetime — timezone is explicitly UTC.
# Safe for arithmetic, comparison, and serialization across timezones.
```

Python 3.12 deprecated `datetime.utcnow()` entirely. Always use the timezone-aware version.

### `__eq__` — Why Tests Can Use `assert result == record`

Because `@dataclass` generates `__eq__`, two `URLRecord` instances are equal if all
their fields match:

```python
record_a = URLRecord(id=1, code="abc", original_url="https://google.com")
record_b = URLRecord(id=1, code="abc", original_url="https://google.com")

print(record_a == record_b)   # True — same field values

# Without @dataclass:
print(record_a == record_b)   # False — Python compares object identity (memory address)
```

This is why `test_save_and_retrieve` can do `assert result == record` — the dataclass
`__eq__` compares field values, not memory addresses.

---

## 4. The Repository Pattern — From First Principles

### The Problem It Solves

Without the Repository Pattern, your business logic talks directly to the database:

```python
class URLService:
    async def shorten(self, url: str) -> URLRecord:
        # Direct SQL — tightly coupled to PostgreSQL
        row = await db.execute(
            "INSERT INTO urls (code, original_url) VALUES ($1, $2) RETURNING *",
            code, url
        )
        return URLRecord(**row)
```

Problems:
1. **Untestable without a database.** To test `shorten()`, you need a real running
   PostgreSQL instance. Tests are slow, fragile, and require infrastructure.
2. **Tightly coupled.** Switching from PostgreSQL to MySQL means rewriting
   `URLService`. The business logic and storage are tangled.
3. **Duplication.** If you add a CLI interface alongside the API, you write the
   same SQL queries again.

### The Solution: An Interface Between Logic and Storage

The Repository Pattern introduces an **abstract interface** that defines *what*
operations exist without specifying *how* they are implemented:

```
URLService  →  URLRepository (interface)
                    ↑
         InMemoryURLRepository   (tests)
         PostgresURLRepository   (production)
         RedisURLRepository      (hypothetical)
```

`URLService` only knows about the interface. It calls `repo.save(record)`. It
doesn't know if that saves to a dict, a PostgreSQL table, or a file on disk.

The concrete implementation is **injected** at startup:

```python
# Tests
service = URLService(repo=InMemoryURLRepository())

# Production
service = URLService(repo=PostgresURLRepository(db_session))
```

Same service. Same tests. Different storage. Zero code changes in business logic.

### The Analogy

> Think of a power socket in a wall. The socket is the interface — it defines the
> shape of the connection (two or three prongs, specific voltage). Every device that
> plugs in gets power, regardless of whether the power comes from a coal plant, a
> solar array, or a wind farm.
>
> `URLService` is the device. `URLRepository` is the socket.
> `InMemoryURLRepository` is solar. `PostgresURLRepository` is coal.
>
> The device doesn't know or care which power source is behind the wall.
> The socket contract is all that matters.

---

## 5. Abstract Base Classes — How Python Enforces Contracts

### What ABC Is

`ABC` (Abstract Base Class) is Python's mechanism for defining interfaces — classes
that declare method signatures without implementing them.

```python
from abc import ABC, abstractmethod


class URLRepository(ABC):
    @abstractmethod
    def save(self, record: URLRecord) -> URLRecord:
        ...
```

Two rules enforced by Python:

**Rule 1 — You cannot instantiate an ABC directly.**
```python
repo = URLRepository()
# TypeError: Can't instantiate abstract class URLRepository
# with abstract methods get_by_code, increment_clicks, next_id, save
```

This is exactly what `test_cannot_instantiate_abstract` verifies. The contract
cannot be bypassed — you must implement all abstract methods.

**Rule 2 — Any subclass must implement all abstract methods.**
```python
class BrokenRepository(URLRepository):
    def save(self, record: URLRecord) -> URLRecord:
        ...
    # forgot to implement get_by_code, increment_clicks, next_id

repo = BrokenRepository()
# TypeError: Can't instantiate abstract class BrokenRepository
# with abstract methods get_by_code, increment_clicks, next_id
```

Python enforces this at instantiation time — not at runtime when the missing
method is first called. You find out immediately, not in production.

### `...` vs `pass` in Abstract Methods

```python
# pass — "do nothing here"
@abstractmethod
def save(self, record: URLRecord) -> URLRecord:
    pass

# ... (ellipsis) — "intentionally not implemented"
@abstractmethod
def save(self, record: URLRecord) -> URLRecord:
    ...
```

Both work identically at runtime. The difference is intent:
- `pass` means "this statement does nothing"
- `...` means "this is a placeholder — deliberately empty"

`...` is the convention for abstract methods, stub functions, and type stubs.
It is universally understood by Python developers as "this is intentionally empty."

### Why Docstrings Are Critical on Abstract Methods

The docstring on an abstract method is the **contract specification**. Every
implementor reads it to understand exactly what their implementation must do.

```python
@abstractmethod
def get_by_code(self, code: str) -> URLRecord | None:
    """
    Find a record by short code.
    Returns None if not found — never raises on missing codes.
    """
    ...
```

"Returns None if not found — never raises" is a critical contract detail.
Without it, one implementation might return `None`, another might raise
`URLNotFoundError`. The service layer can't predict which — silent bugs.

With the docstring, the contract is clear: `None` on miss, no exceptions.

---

## 6. The Repository Interface — `URLRepository`

### The Four Operations

```python
from abc import ABC, abstractmethod
from app.domain.models import URLRecord


class URLRepository(ABC):

    @abstractmethod
    def save(self, record: URLRecord) -> URLRecord:
        """
        Persist a new URL record.
        Returns the saved record with any storage-assigned fields populated.
        """
        ...

    @abstractmethod
    def get_by_code(self, code: str) -> URLRecord | None:
        """
        Find a record by short code.
        Returns None if not found — never raises on missing codes.
        """
        ...

    @abstractmethod
    def increment_clicks(self, code: str) -> None:
        """
        Increment the click counter for a short code.
        Silently ignores codes that don't exist.
        """
        ...

    @abstractmethod
    def next_id(self) -> int:
        """
        Return the next available integer ID.
        Must be unique and monotonically increasing.
        """
        ...
```

### Why `next_id()` Is on the Repository

The Base62 encoder takes an integer and returns a short code. That integer
must come from somewhere — and it must be unique.

In production (Phase 6), PostgreSQL auto-increment gives you a unique ID when
you insert a row. The repository returns it as part of the saved record.

In tests, the in-memory repository manages its own counter. The service calls
`repo.next_id()`, gets an integer, encodes it with Base62, and that becomes the code.

Putting `next_id()` on the repository keeps ID generation consistent regardless
of which concrete implementation is behind the interface.

### Why Methods Are Synchronous Here

The in-memory implementation has no I/O — it just reads and writes a dict.
Synchronous methods are correct.

In Phase 6, the Postgres implementation will have `async def` methods — awaiting
database queries. The repository interface will be updated to `async` at that point,
and the service layer will `await` the calls.

For now, synchronous is correct and simpler.

---

## 7. In-Memory Implementation — `InMemoryURLRepository`

### Why In-Memory First

The in-memory implementation serves two purposes:

**1. Development without infrastructure.** You can run the entire app without
PostgreSQL installed. `app.state.repo = InMemoryURLRepository()` and everything
works. Data lives in RAM and disappears on restart — that's fine for development.

**2. Fast tests.** Tests that use `InMemoryURLRepository` run in milliseconds.
Tests that use a real database take seconds per test. A test suite of 200 tests
with a real database takes minutes. With in-memory, it takes seconds.

This is a core testing principle: **test at the lowest level possible.**
Test business logic without infrastructure. Test infrastructure separately.

### The Implementation

```python
from app.domain.models import URLRecord
from app.domain.repositories import URLRepository


class InMemoryURLRepository(URLRepository):

    def __init__(self) -> None:
        # Primary store: code → URLRecord
        # A dict gives O(1) lookup by code — same as a database index on the code column.
        self._store: dict[str, URLRecord] = {}

        # ID counter: starts at 0, incremented before returning
        # next_id() returns 1 on first call, 2 on second, etc.
        self._counter: int = 0

    def save(self, record: URLRecord) -> URLRecord:
        self._store[record.code] = record
        return record

    def get_by_code(self, code: str) -> URLRecord | None:
        # dict.get() returns None if key not found — not KeyError
        return self._store.get(code)

    def increment_clicks(self, code: str) -> None:
        if code in self._store:
            self._store[code].click_count += 1
        # Unknown codes are silently ignored — matches the interface contract

    def next_id(self) -> int:
        self._counter += 1
        return self._counter
```

### Why `dict.get(code)` Not `dict[code]`

```python
# dict[code] — raises KeyError if key not found
return self._store["missing_code"]   # KeyError: 'missing_code'

# dict.get(code) — returns None if key not found
return self._store.get("missing_code")  # None
```

The repository contract says: "returns None if not found — never raises."
`dict.get()` fulfills this contract. `dict[code]` violates it.

### Each Test Gets a Fresh Repository

Every test function creates `InMemoryURLRepository()` from scratch:

```python
def test_save_and_retrieve() -> None:
    repo = InMemoryURLRepository()   # fresh, empty
    ...

def test_increment_clicks() -> None:
    repo = InMemoryURLRepository()   # fresh, empty — no leftover data from above
    ...
```

This is **test isolation** — tests don't share state. If `test_save_and_retrieve`
creates a record, `test_increment_clicks` doesn't see it. Tests can run in any
order and produce identical results.

---

## 8. Testing the Repository Pattern

### Test Against the Interface, Not the Implementation

The most important testing decision in Phase 3:

```python
# CORRECT — typed as the interface
def test_save_and_retrieve() -> None:
    repo: URLRepository = InMemoryURLRepository()
    ...

# WRONG — typed as the concrete class
def test_save_and_retrieve() -> None:
    repo: InMemoryURLRepository = InMemoryURLRepository()
    ...
```

By typing as `URLRepository`, the test proves the **interface contract** works.
If you accidentally call a method that only exists on `InMemoryURLRepository`
but not on `URLRepository`, your IDE and type checker will catch it immediately.

More importantly: when `PostgresURLRepository` is built in Phase 6, you can run
these exact same tests against it. If they pass, the implementation is correct.
The tests are testing the *contract*, not the *implementation details*.

### The Six Tests

```
test_save_and_retrieve
```
Proves the fundamental contract: save a record, retrieve it by code, get back
the same object. The `@dataclass`-generated `__eq__` makes `assert result == record`
work correctly.

```
test_get_nonexistent_returns_none
```
Proves the "never raises" part of the contract. Calling `get_by_code` with an
unknown code must return `None`, not raise a `KeyError` or `URLNotFoundError`.

```
test_increment_clicks
```
Proves click counting works. Save a record with `click_count=0`, call
`increment_clicks`, retrieve and verify `click_count==1`.

```
test_increment_nonexistent_code
```
Proves silently-ignores behaviour. Incrementing an unknown code must not crash.
This test has no assertion — it just verifies no exception is raised.

```
test_next_id_increments
```
Proves IDs are unique and monotonically increasing. Three consecutive calls must
return 1, 2, 3 — in that order. This guarantees Base62 will produce unique codes.

```
test_cannot_instantiate_abstract
```
Proves the ABC enforcement works. `URLRepository()` must raise `TypeError`.
This verifies that the abstract contract cannot be bypassed — any class claiming
to implement `URLRepository` must implement all four methods.

---

## 9. Design Decisions Explained

### Why Not Use `@dataclass(frozen=True)`?

`frozen=True` makes the dataclass immutable — no attribute can be changed after
creation. At first glance, this sounds good for a record.

But `click_count` needs to be mutated in place:

```python
self._store[code].click_count += 1   # mutates the stored record directly
```

With `frozen=True`, this raises `FrozenInstanceError`. You would need to create
a new `URLRecord` with the updated count every time a click is recorded —
unnecessary overhead.

For now, mutable is correct. In the Postgres implementation, click counts will
be an `UPDATE` query anyway, not an in-memory mutation.

### Why `next_id()` Increments Before Returning

```python
def next_id(self) -> int:
    self._counter += 1   # increment first
    return self._counter  # then return
```

Counter starts at 0. First call: increment to 1, return 1.
Second call: increment to 2, return 2.

If you returned first and incremented after:

```python
def next_id(self) -> int:
    result = self._counter
    self._counter += 1
    return result         # returns 0 on first call
```

You'd return 0 on the first call. `base62.encode(0)` returns `"0"`. Short codes
starting at `"0"` are confusing. IDs should start at 1. Increment-then-return
gives you 1-based IDs cleanly.

### Why the Repository Returns `URLRecord` From `save()`

```python
def save(self, record: URLRecord) -> URLRecord:
    ...
    return record
```

In the in-memory implementation, the input and output are the same object.
Returning it feels redundant.

In the Postgres implementation (Phase 6), the database assigns the ID (via
`SERIAL` or `BIGSERIAL`). The record you INSERT doesn't have an ID yet.
The record that comes back from the database does. The service layer needs that ID
to call `base62.encode(id)`. The `save()` returning a record is the mechanism for
getting that ID back.

```python
# Phase 6 will look like this:
async def save(self, record: URLRecord) -> URLRecord:
    result = await db.execute(
        "INSERT INTO urls (code, original_url) VALUES ($1, $2) RETURNING id",
        record.code, record.original_url
    )
    record.id = result["id"]   # DB-assigned ID is now on the record
    return record              # caller gets the record with ID populated
```

Designing the interface to return `URLRecord` from `save()` now means Phase 6
requires zero changes to the interface or the service layer.

---

## 10. The Final Implementation

### `app/domain/models.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class URLRecord:
    """
    Represents one stored URL mapping.

    Pure data — no database columns, no HTTP concerns, no framework dependencies.
    The domain model is the source of truth for what a shortened URL looks like.
    """
    id: int
    code: str
    original_url: str
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    click_count: int = 0
```

### `app/domain/repositories.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from app.domain.models import URLRecord


class URLRepository(ABC):
    """
    Abstract interface for URL storage.

    Defines the contract that all concrete implementations must fulfill.
    The service layer depends only on this interface — never on a concrete class.
    """

    @abstractmethod
    def save(self, record: URLRecord) -> URLRecord:
        """
        Persist a new URL record.
        Returns the saved record with any storage-assigned fields populated.
        """
        ...

    @abstractmethod
    def get_by_code(self, code: str) -> URLRecord | None:
        """
        Find a record by short code.
        Returns None if not found — never raises on missing codes.
        """
        ...

    @abstractmethod
    def increment_clicks(self, code: str) -> None:
        """
        Increment the click counter for a short code.
        Silently ignores codes that do not exist.
        """
        ...

    @abstractmethod
    def next_id(self) -> int:
        """
        Return the next available integer ID.
        Must be unique and monotonically increasing across all calls.
        """
        ...
```

### `app/domain/memory.py`

```python
from __future__ import annotations
from app.domain.models import URLRecord
from app.domain.repositories import URLRepository


class InMemoryURLRepository(URLRepository):
    """
    Dict-based in-memory implementation of URLRepository.

    Used in tests and local development. Data lives in RAM —
    all state is lost on process restart. No infrastructure required.
    """

    def __init__(self) -> None:
        self._store: dict[str, URLRecord] = {}
        self._counter: int = 0

    def save(self, record: URLRecord) -> URLRecord:
        self._store[record.code] = record
        return record

    def get_by_code(self, code: str) -> URLRecord | None:
        return self._store.get(code)

    def increment_clicks(self, code: str) -> None:
        if code in self._store:
            self._store[code].click_count += 1

    def next_id(self) -> int:
        self._counter += 1
        return self._counter
```

---

## 11. The Final Tests

```python
# tests/test_repository.py

import pytest
from app.domain.memory import InMemoryURLRepository
from app.domain.models import URLRecord
from app.domain.repositories import URLRepository


def test_save_and_retrieve() -> None:
    repo: URLRepository = InMemoryURLRepository()
    record = URLRecord(id=1, code="abc123", original_url="https://google.com")

    repo.save(record)
    result = repo.get_by_code("abc123")

    assert result == record


def test_get_nonexistent_returns_none() -> None:
    repo: URLRepository = InMemoryURLRepository()

    result = repo.get_by_code("does-not-exist")

    assert result is None


def test_increment_clicks() -> None:
    repo: URLRepository = InMemoryURLRepository()
    record = URLRecord(id=1, code="abc123", original_url="https://google.com")
    repo.save(record)

    repo.increment_clicks("abc123")
    result = repo.get_by_code("abc123")

    assert result is not None
    assert result.click_count == 1


def test_increment_nonexistent_code() -> None:
    repo: URLRepository = InMemoryURLRepository()
    repo.increment_clicks("missing-code")   # must not raise


def test_next_id_increments() -> None:
    repo: URLRepository = InMemoryURLRepository()

    assert repo.next_id() == 1
    assert repo.next_id() == 2
    assert repo.next_id() == 3


def test_cannot_instantiate_abstract() -> None:
    with pytest.raises(TypeError):
        URLRepository()   # type: ignore[abstract]
```

---

## 12. What Phase 3 Does NOT Have Yet

- **No service layer** — `URLService` doesn't exist yet. Phase 4 builds it.
  The service is what wires Base62 + repository together into business operations.
- **No FastAPI integration** — the repository is not attached to `app.state` yet.
  That happens in Phase 5 when routes are added.
- **No real database** — `InMemoryURLRepository` is the only implementation.
  `PostgresURLRepository` is built in Phase 6.
- **No async** — the repository is synchronous. Phase 6 converts it to async
  when real I/O (database queries) is introduced.

---

## 13. Phase 4 Preview

Phase 4 builds the **service layer** — `app/domain/services.py`.

`URLService` is the class that orchestrates all business operations. It holds:
- A reference to `URLRepository` (injected, not hardcoded)
- The business logic for shortening a URL, redirecting, and fetching stats

```python
class URLService:
    def __init__(self, repo: URLRepository) -> None:
        self._repo = repo

    def shorten(self, original_url: str) -> URLRecord:
        next_id = self._repo.next_id()
        code = encode(next_id)          # Base62 from Phase 2
        record = URLRecord(
            id=next_id,
            code=code,
            original_url=original_url,
        )
        return self._repo.save(record)

    def redirect(self, code: str) -> URLRecord:
        record = self._repo.get_by_code(code)
        if record is None:
            raise URLNotFoundError(code)
        self._repo.increment_clicks(code)
        return record

    def get_stats(self, code: str) -> URLRecord:
        record = self._repo.get_by_code(code)
        if record is None:
            raise URLNotFoundError(code)
        return record
```

The service raises domain exceptions (`URLNotFoundError`). The API layer catches
them and converts to HTTP responses (`404 Not Found`). Those are different concerns
in different layers — the service never knows about HTTP.

**Testing Phase 4 is where it gets interesting.** You test `URLService` with
`InMemoryURLRepository` — no database, no HTTP, no FastAPI. The tests run in
milliseconds and cover every business rule completely.

---

*Phase 3 complete. 6 tests passing. The domain layer is solid.*
*The repository interface is the contract that makes the entire application testable.*
*Every layer built after this sits on top of what was designed here.*
