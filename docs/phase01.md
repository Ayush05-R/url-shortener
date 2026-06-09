# Phase 1 — Project Scaffold
### URL Shortener Build Log

> This document explains everything built in Phase 1 — not just what was created,
> but why each decision was made, what each tool does internally, and how it all
> connects. Read this before touching Phase 2.

---

## Table of Contents

1. [What Phase 1 Actually Built](#1-what-phase-1-actually-built)
2. [Project Structure — Why Layered Architecture](#2-project-structure)
3. [uv — The Package Manager](#3-uv-the-package-manager)
4. [pyproject.toml — The Project Manifest](#4-pyprojecttoml)
5. [pydantic-settings — Config Management](#5-pydantic-settings)
6. [Custom Exceptions — The Exception Hierarchy](#6-custom-exceptions)
7. [FastAPI App + Lifespan](#7-fastapi-app--lifespan)
8. [The Health Endpoint](#8-the-health-endpoint)
9. [pytest — Testing Setup](#9-pytest-testing-setup)
10. [conftest.py — Fixtures](#10-conftestpy-fixtures)
11. [Git Branching — The Workflow](#11-git-branching)
12. [What Phase 1 Does NOT Have Yet](#12-what-phase-1-does-not-have-yet)
13. [Phase 1 File Reference](#13-phase-1-file-reference)

---

## 1. What Phase 1 Actually Built

Phase 1 built **zero business logic**. No URL shortening. No database. No algorithms.

That is intentional. Phase 1 builds the **foundation** — the structure, config, and
tooling that every future phase sits on top of. Getting this right means every phase
after this is easier, testable, and doesn't collapse when you add something new.

Here is the complete list of what Phase 1 delivers:

- A clean, layered folder structure that scales as the project grows
- Dependency management with `uv` — fast, locked, reproducible
- Config management that reads from `.env` — no hardcoded values anywhere
- A custom exception hierarchy — domain errors have names, not generic messages
- A bare FastAPI app with a `lifespan` hook ready for startup/shutdown logic
- One working endpoint: `GET /health`
- A working test suite with one passing test
- A Git branch workflow

---

## 2. Project Structure

### The Folder Layout

```
url_shortener/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # all configuration lives here
│   ├── exceptions.py        # custom exception hierarchy
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       └── __init__.py  # routes added in Phase 5
│   ├── domain/
│   │   └── __init__.py      # models + repository interface — Phase 3
│   ├── infrastructure/
│   │   └── __init__.py      # database + cache clients — Phase 6, 7
│   └── algorithms/
│       └── __init__.py      # base62, bloom filter, LRU — Phase 2, 7
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # shared pytest fixtures
│   └── test_health.py       # first passing test
├── .env                     # real secrets — NEVER committed
├── .env.example             # template showing what vars are needed
├── .gitignore
├── pyproject.toml
└── uv.lock
```

### Why This Structure — Layered Architecture

Every folder in `app/` represents a **layer**. Each layer has one responsibility and
talks only to the layer below it. This is called **Separation of Concerns**.

```
Request → API layer (routes)
              ↓
         Domain layer (business logic, models)
              ↓
         Infrastructure layer (database, cache)
```

**`api/`** — HTTP concerns only. Receives requests, validates input, returns responses.
Knows nothing about databases or algorithms. If FastAPI were swapped for Flask tomorrow,
only this layer changes.

**`domain/`** — business logic. What a URL record looks like. What it means to shorten
a URL. What rules apply. Zero knowledge of HTTP or databases.

**`infrastructure/`** — external systems. Database connections, Redis client,
actual SQL queries. If you swap PostgreSQL for MongoDB, only this layer changes.
The domain layer doesn't care.

**`algorithms/`** — pure computation. Base62 encoding, Bloom filter, LRU cache.
No framework. No database. Just Python functions and data structures. Completely
isolated — testable without starting FastAPI at all.

### Why `__init__.py` in Every Folder

Python only treats a folder as a **package** (importable module) if it contains
`__init__.py`. Without it, `from app.config import settings` raises `ModuleNotFoundError`
because Python doesn't know `app` is a package.

The file can be completely empty. Its presence is what matters.

```python
# This import works:
from app.config import settings      # because app/__init__.py exists

# Without __init__.py this fails with:
# ModuleNotFoundError: No module named 'app'
```

---

## 3. uv — The Package Manager

### What It Replaces

Before `uv`, Python projects used:
- `pip` to install packages
- `virtualenv` or `venv` to create isolated environments
- `pip-tools` or `poetry` to lock dependency versions

`uv` replaces all three in one tool. Written in Rust — significantly faster than pip.

### Key Commands

```bash
uv add fastapi[standard]          # add a production dependency
uv add --dev pytest httpx         # add a dev-only dependency
uv sync                           # install all production deps
uv sync --dev                     # install everything including dev deps
uv run pytest tests/ -v           # run a command inside the venv
uv pip list                       # list installed packages
```

### Why `uv run` Instead of Just `pytest`

When you run `pytest` directly, you might be using the system Python — not your
project's virtual environment. `uv run` ensures the command runs inside the correct
isolated environment every time, regardless of your system setup.

### The Lock File — `uv.lock`

When you run `uv add`, two things happen:

1. The package is added to `pyproject.toml` with a minimum version constraint
2. `uv.lock` is updated with the **exact** version of every package installed,
   including all transitive dependencies (dependencies of dependencies)

```
pyproject.toml says: "fastapi>=0.111.0"  ← "anything this version or newer"
uv.lock says:        "fastapi==0.115.2"  ← "exactly this version"
```

`uv.lock` is committed to git. When your teammate (or your deployment server)
runs `uv sync`, they get **identical** versions. Not compatible — identical.
This eliminates "works on my machine" bugs caused by version differences.

---

## 4. pyproject.toml

### What It Is

`pyproject.toml` is the single source of truth for your Python project. It replaces
`setup.py`, `requirements.txt`, `setup.cfg`, and `tox.ini` — all in one file.

### The Structure

```toml
[project]
name = "url-shortener"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi[standard]",
    "pydantic-settings>=2.14.1",
]

[dependency-groups]
dev = [
    "httpx>=0.28.1",
    "pytest>=9.0.3",
    "pytest-asyncio>=1.4.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

### Production vs Dev Dependencies

`dependencies` — what the app needs to **run** in production.
`[dependency-groups] dev` — what you need to **develop and test** locally.

When you deploy to a server:
```bash
uv sync          # installs only production deps — no pytest, no httpx
```

When developing locally:
```bash
uv sync --dev    # installs everything
```

Why does this matter? Your production Docker image stays small and has fewer
packages — fewer packages means a smaller attack surface for security vulnerabilities.

### `asyncio_mode = "auto"`

This tells `pytest-asyncio` to automatically treat all `async def test_*` functions
as async tests without requiring `@pytest.mark.asyncio` on every single one.

Without it, every async test needs the decorator manually:
```python
# Without asyncio_mode = "auto" — tedious
@pytest.mark.asyncio
async def test_something():
    ...

# With asyncio_mode = "auto" — clean
async def test_something():
    ...
```

---

## 5. pydantic-settings

### What It Solves

Every application needs configuration — database URLs, API keys, feature flags.
The wrong way to handle this is hardcoding values:

```python
# WRONG — never do this
DATABASE_URL = "postgresql://postgres:mypassword@localhost/mydb"
SECRET_KEY = "super_secret_123"
```

Problems: secrets end up in git history, different environments (dev, staging, prod)
need different values, changing a value means editing code and redeploying.

The correct approach: **read config from environment variables** at runtime.

### How pydantic-settings Works

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",           # read from this file if it exists
        env_file_encoding="utf-8",
        case_sensitive=False,      # DATABASE_URL and database_url both work
    )

    app_name: str = "URL Shortener"    # default value
    debug: bool = False
    base_url: str = "http://localhost:8000"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/urlshortener"
    redis_url: str = "redis://localhost:6379/0"


settings = Settings()
```

When `Settings()` is called, pydantic-settings does this in order:

```
1. Check actual environment variables (os.environ)
2. If not found, check .env file
3. If not found, use the default value in the class
4. If no default, raise ValidationError
```

### The `.env` and `.env.example` Pattern

`.env` holds your **real** values — actual passwords, real database URLs:
```bash
DEBUG=true
DATABASE_URL=postgresql+asyncpg://postgres:mypassword@localhost:5432/urlshortener
```

`.env.example` is a **template** committed to git — shows what variables exist
without exposing real values:
```bash
DEBUG=false
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/urlshortener
```

`.env` is in `.gitignore` — **never committed**. If a real password gets pushed
to GitHub, even once, even if you delete it in the next commit, it is permanently
in the git history and must be considered compromised.

### Using Settings Across the App

```python
# Any file in the project
from app.config import settings

print(settings.app_name)      # "URL Shortener"
print(settings.debug)         # False
```

`settings = Settings()` at the bottom of `config.py` creates one instance at
module import time. Every import gets the same object. No repeated env file reads.

### Type Safety and Validation

pydantic-settings validates types automatically:

```bash
# .env file
DEBUG=not_a_bool
```

```python
# This raises ValidationError at startup — not silently at runtime
settings = Settings()
# ValidationError: debug: Input should be a valid boolean
```

Your app crashes immediately at startup with a clear error rather than silently
misbehaving hours later when `debug` is used somewhere.

---

## 6. Custom Exceptions

### Why Not Use Built-in Exceptions

```python
# Bad — what does this tell you?
raise ValueError("not found")
raise Exception("something went wrong")
```

Generic exceptions carry no domain meaning. You cannot `except URLNotFoundError`
to handle one specific case — you have to catch `ValueError` and hope nothing
else raises it, or inspect the message string (fragile).

### The Exception Hierarchy

```python
class URLShortenerError(Exception):
    """Base exception for all application errors."""
    pass


class URLNotFoundError(URLShortenerError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Short code '{code}' not found.")


class URLExpiredError(URLShortenerError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Short code '{code}' has expired.")


class InvalidURLError(URLShortenerError):
    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        super().__init__(f"Invalid URL '{url}': {reason}")
```

### How the Hierarchy Works

```
Exception
    └── URLShortenerError          ← catch ALL app errors
            ├── URLNotFoundError   ← catch specifically "not found"
            ├── URLExpiredError    ← catch specifically "expired"
            └── InvalidURLError   ← catch specifically "bad URL"
```

This lets you be as specific or as broad as you need:

```python
try:
    url = service.redirect(code)
except URLNotFoundError as e:
    # handle specifically — return 404
    raise HTTPException(status_code=404, detail=str(e))
except URLExpiredError as e:
    # handle specifically — return 410 Gone
    raise HTTPException(status_code=410, detail=str(e))
except URLShortenerError as e:
    # catch anything else from the app — return 500
    raise HTTPException(status_code=500, detail=str(e))
```

### Attaching Data to Exceptions

Notice each exception stores the relevant data as an attribute:

```python
except URLNotFoundError as e:
    print(e.code)    # the actual short code that wasn't found
```

This lets the exception handler access structured data rather than parsing
a message string. Structured data is always better than string parsing.

---

## 7. FastAPI App + Lifespan

### The Bare App

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP: runs once before any request is processed
    yield
    # SHUTDOWN: runs once after all requests are done


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)
```

### What `lifespan` Is

`lifespan` is a context manager that wraps the entire lifetime of the FastAPI app.
Everything before `yield` runs at **startup**. Everything after `yield` runs at
**shutdown**.

```
App starts
    → lifespan enters (code before yield runs)
    → yield
    → app processes requests (this can run for hours/days)
    → app shuts down (Ctrl+C or server stop)
    → lifespan exits (code after yield runs)
```

Right now both sections are empty. In later phases, startup will initialize the
connection pools and Redis client. Shutdown will drain them cleanly.

### Why `lifespan` and Not `@app.on_event("startup")`

`@app.on_event("startup")` is the old way — deprecated in recent FastAPI versions.
`lifespan` is the current standard because it uses a context manager, which guarantees
the shutdown code always runs — even if startup raises an exception.

```python
# OLD — deprecated
@app.on_event("startup")
async def startup():
    app.state.pool = create_pool()

@app.on_event("shutdown")
async def shutdown():
    app.state.pool.close()   # what if startup crashed? this never runs.

# NEW — lifespan guarantees shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = create_pool()
    try:
        yield
    finally:
        app.state.pool.close()   # ALWAYS runs, even if something crashed
```

### `app.state`

`app.state` is a simple namespace attached to the FastAPI app instance. Use it to
store anything that needs to live for the entire application lifetime —
connection pools, Redis clients, config objects.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = DatabaseConnectionPool(max_connections=20)
    yield
    # pool is cleaned up when app stops
```

Routes access it via `request.app.state`:

```python
@app.get("/something")
async def route(request: Request):
    pool = request.app.state.pool
```

This is the correct, non-global way to share resources across routes.

---

## 8. The Health Endpoint

```python
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

Simple. But every production API has one. Here is why it matters:

**Load balancers** hit `/health` every few seconds. If it returns non-200, the load
balancer stops sending traffic to that instance and routes to a healthy one.

**Deployment systems** (Kubernetes, Fly.io, Railway) hit `/health` to know when your
app has finished starting up and is ready to receive traffic.

**Monitoring** uses it to alert on-call engineers when the app goes down.

In later phases, the health endpoint will report pool status, database connectivity,
and Redis connectivity — not just "ok". A rich health endpoint tells you exactly
what is wrong without SSH-ing into the server.

### Return Type Annotation

```python
async def health() -> dict[str, str]:
```

FastAPI reads this return type and validates the response against it.
If the function returns something that doesn't match `dict[str, str]`,
FastAPI raises a server error immediately. This catches bugs at the API boundary.

---

## 9. pytest — Testing Setup

### What pytest Is

pytest is Python's standard testing framework. You write test functions, pytest
finds and runs them, and reports which passed and which failed.

Convention: any file named `test_*.py` and any function named `test_*` is
automatically discovered and run.

```bash
uv run pytest tests/ -v    # run all tests in tests/, verbose output
uv run pytest tests/test_health.py   # run one specific file
uv run pytest -k "health"  # run tests whose name contains "health"
```

### The `-v` Flag

Without `-v` (verbose), pytest shows a dot per passing test and `F` per failure.
With `-v`, it shows the full test name and PASSED/FAILED. Always use `-v` while
developing — the full names tell you exactly what passed.

### pytest-asyncio

FastAPI routes and services are `async` functions. Regular pytest cannot run
`async def` test functions — it doesn't know how to drive an event loop.

`pytest-asyncio` adds async support to pytest. With `asyncio_mode = "auto"` in
`pyproject.toml`, every `async def test_*` function automatically runs inside
an event loop.

---

## 10. conftest.py — Fixtures

### What a Fixture Is

A fixture is a reusable piece of setup that tests can request. Instead of
repeating setup code in every test function, you define it once in a fixture
and tests declare they need it by name.

```python
# Without fixtures — repeated setup
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200

async def test_something_else():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/other")
        assert response.status_code == 200
```

```python
# With fixtures — setup once, used everywhere
@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

async def test_health(client):          # just declare "client" as a parameter
    response = await client.get("/health")
    assert response.status_code == 200

async def test_something_else(client):  # same client, zero repeated setup
    response = await client.get("/other")
    assert response.status_code == 200
```

pytest sees `client` as a parameter name, finds the matching fixture, runs it,
and passes the yielded value to the test.

### Why `conftest.py` Specifically

pytest has a discovery rule: any fixture defined in `conftest.py` is automatically
available to every test in the same directory and all subdirectories. No imports needed.

If you put a fixture in `test_health.py`, only tests in that file can use it.
Put it in `conftest.py` and every test file in `tests/` can use it.

**The filename must be exactly `conftest.py`.** pytest looks for this filename
specifically. `conf.py`, `confest.py`, `conftest_test.py` — all ignored.
(This is the typo that caused the error during setup.)

### `ASGITransport` — No Server Needed

```python
transport=ASGITransport(app=app)
```

`ASGITransport` tells `httpx` to send requests directly to the FastAPI app object
in-process — no server, no port, no network. The test runs entirely in memory.

This is why tests don't require `uvicorn main:app` to be running. The test
infrastructure drives the app directly.

### `yield` in Fixtures

The fixture uses `yield` instead of `return`:

```python
@pytest.fixture
async def client():
    async with AsyncClient(...) as ac:
        yield ac          # test runs here
    # cleanup happens here — AsyncClient closes
```

Everything before `yield` is setup. Everything after `yield` is teardown.
pytest runs each test's teardown automatically after the test completes —
pass, fail, or error. The `AsyncClient` is always properly closed.

---

## 11. Git Branching

### The Workflow Used in This Project

```
main ──────────────────────────────●──────── (always stable)
                                   │
feat/project-scaffold ──────●──●──●          (your work branch)
```

Every phase gets its own branch:

```bash
# Start a phase
git checkout main
git pull origin main
git checkout -b feat/phase-name

# Work, commit as you go
git add .
git commit -m "feat: meaningful description"

# Phase done, tests green, merge back
git checkout main
git merge feat/phase-name
git push origin main
git branch -d feat/phase-name
```

### Branch Naming Convention

| Prefix | When to use |
|---|---|
| `feat/` | New feature or phase |
| `fix/` | Bug fix |
| `chore/` | Non-functional changes (deps, config, docs) |
| `refactor/` | Code restructuring with no behaviour change |

### Commit Message Convention

```
feat: add base62 encoder and decoder
fix: handle empty string in base62 decode
chore: add sqlalchemy to dependencies
test: add unit tests for base62 edge cases
refactor: extract url validation to domain service
```

Format: `type: short description in present tense, lowercase, no period`

This is the **Conventional Commits** standard used at most tech companies.
Your git log becomes readable history:

```
git log --oneline

a3f2c1b feat: add bloom filter with configurable false positive rate
9d1e4a2 test: add integration tests for redirect endpoint
7c0b3f5 feat: add postgres repository implementation
2a8d1e9 feat: add base62 encoder and decoder
e4f9b2c feat: project scaffold with config and health endpoint
```

---

## 12. What Phase 1 Does NOT Have Yet

Be clear on what is missing — this prevents confusion in later phases:

- **No database** — `DATABASE_URL` exists in config but nothing connects to it
- **No Redis** — `REDIS_URL` exists in config but nothing connects to it
- **No business logic** — no URL shortening, no redirecting, no stats
- **No domain models** — `URLRecord` doesn't exist yet
- **No algorithms** — Base62, Bloom filter, LRU cache all come later
- **No real routes** — only `/health` exists
- **No rate limiting** — added in Phase 5
- **No Docker** — added in Phase 8

The `domain/`, `infrastructure/`, `algorithms/` folders are intentionally empty.
Their `__init__.py` files exist only to make them valid Python packages.

---

## 13. Phase 1 File Reference

### `app/config.py` — Full Explanation

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",              # look for .env in project root
        env_file_encoding="utf-8",    # handle special characters
        case_sensitive=False,         # DATABASE_URL == database_url
    )

    # App settings
    app_name: str = "URL Shortener"   # str type, default value
    debug: bool = False               # bool — pydantic converts "true"/"false"
    base_url: str = "http://localhost:8000"  # used to build short URLs

    # Future phases — values exist in config now, used when the phase is built
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/urlshortener"
    redis_url: str = "redis://localhost:6379/0"
    shorten_rate_limit_calls: int = 10
    shorten_rate_limit_period: int = 60
    redirect_rate_limit_calls: int = 60
    redirect_rate_limit_period: int = 60


settings = Settings()   # single instance, imported across the app
```

### `app/exceptions.py` — Full Explanation

```python
class URLShortenerError(Exception):
    """
    Base class. Catch this to handle any app-level error generically.
    Never raised directly — always raise a specific subclass.
    """
    pass


class URLNotFoundError(URLShortenerError):
    """
    Raised when a short code is looked up but doesn't exist in storage.
    Maps to HTTP 404 in the API layer.
    """
    def __init__(self, code: str) -> None:
        self.code = code                          # structured data — not just a string
        super().__init__(f"Short code '{code}' not found.")


class URLExpiredError(URLShortenerError):
    """
    Raised when a short code exists but its TTL has passed.
    Maps to HTTP 410 Gone in the API layer.
    410 means "this existed but is permanently gone" — more specific than 404.
    """
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Short code '{code}' has expired.")


class InvalidURLError(URLShortenerError):
    """
    Raised when a submitted URL fails validation.
    Maps to HTTP 422 Unprocessable Entity in the API layer.
    """
    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        super().__init__(f"Invalid URL '{url}': {reason}")
```

### `app/main.py` — Full Explanation

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 6: initialize database connection pool here
    # Phase 7: initialize Redis client here
    yield
    # Phase 6: drain connection pool here
    # Phase 7: close Redis client here


app = FastAPI(
    title=settings.app_name,    # shown in /docs Swagger UI
    debug=settings.debug,       # enables detailed error responses when True
    lifespan=lifespan,          # registers the startup/shutdown hook
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

### `tests/conftest.py` — Full Explanation

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture                  # decorator: register this function as a fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),  # drive app in-process, no server
        base_url="http://test",            # fake base URL for request building
    ) as ac:
        yield ac                           # test receives the AsyncClient here
    # AsyncClient closes here automatically
```

### `tests/test_health.py` — Full Explanation

```python
import pytest


async def test_health_returns_ok(client):   # "client" matches the fixture name
    response = await client.get("/health")  # make a real HTTP GET to /health
    assert response.status_code == 200      # assert the response code
    assert response.json() == {"status": "ok"}  # assert the response body
```

---

## What Comes Next — Phase 2 Preview

Phase 2 is the first piece of real logic: the **Base62 encoder**.

A short code like `aB3xY7z` is not random. It is an auto-incrementing integer ID
(1, 2, 3...) from the database, converted to base62 (digits 0-9 + lowercase a-z +
uppercase A-Z = 62 characters).

Why base62? Because it produces short, URL-safe strings. ID 1000000 in base62
is `4c92` — 4 characters. In base 10 it is 7 characters. In base 2 it is 20 characters.

Phase 2 is pure Python — no FastAPI, no database, no config. Just a function that
takes an integer and returns a string, and a function that takes a string and returns
an integer. And tests that prove they work.

**This is where the DSA begins.**

---

*Phase 1 complete. One green test. Clean git history. Solid foundation.*
*Every line of business logic built in future phases sits on top of what was built here.*
