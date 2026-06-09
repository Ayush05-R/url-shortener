# Python Async Production Patterns — Complete Reference
### Singleton · Thread Safety · Connection Pools · Rate Limiting · FastAPI Dependency Injection

> This document is a complete, internals-first reference. Every concept is explained from
> first principles — not just what to do, but exactly why, what goes wrong when you don't,
> and how production engineers actually think about these problems.

---

## Table of Contents

1. [Python's Object Creation Pipeline — The Foundation](#1-pythons-object-creation-pipeline)
2. [The Singleton Pattern — From Internals Up](#2-the-singleton-pattern)
3. [Thread Safety in Async — Why `threading.Lock` Is Dangerous](#3-thread-safety-in-async)
4. [The Async Event Loop — What "Blocking" Actually Means](#4-the-async-event-loop)
5. [Connection Pools — Why `list` Fails and `asyncio.Queue` Wins](#5-connection-pools)
6. [Context Managers — Structural Resource Safety](#6-context-managers)
7. [Singleton as Antipattern — The Full Case Against It](#7-singleton-as-antipattern)
8. [Multi-Pool Architecture in FastAPI](#8-multi-pool-architecture)
9. [Sliding Window Rate Limiter — From Algorithm to Production](#9-sliding-window-rate-limiter)
10. [Mini Project — URL Shortener](#10-mini-project-url-shortener)
11. [Theoretical Q&A — Full Answers](#11-theoretical-qa)
12. [Quick Reference](#12-quick-reference)

---

## 1. Python's Object Creation Pipeline

Before Singleton makes any sense, you need to understand how Python actually builds objects.
Most developers think `ClassName()` calls `__init__`. That is wrong. Here is the full pipeline.

### The Three-Step Process

When you write `DatabaseConnectionPool()`, Python does this in order:

```
Step 1: Find the metaclass
        Python looks at the class definition for metaclass=...
        If none is set, it uses the default: type

Step 2: Call metaclass.__call__(cls, *args, **kwargs)
        This is what actually runs when you write ClassName()

Step 3: Inside type.__call__:
        a) obj = cls.__new__(cls, *args, **kwargs)   # allocate memory, create object
        b) if isinstance(obj, cls):
               cls.__init__(obj, *args, **kwargs)    # initialise the object
        c) return obj
```

### `__new__` vs `__init__` — The Exact Difference

| | `__new__` | `__init__` |
|---|---|---|
| Job | **Creates** the object. Allocates memory. Returns a new instance. | **Initialises** the object. Sets attributes. Returns nothing. |
| When it runs | Before `__init__` | After `__new__` |
| What it receives | The **class** itself as first arg (`cls`) | The **instance** as first arg (`self`) |
| Can it prevent object creation? | Yes — return something else or `None` | No — object already exists |

### Why This Matters for Singleton

Singleton works by **intercepting Step 2**. When you override `__call__` on the metaclass,
you get to decide whether Step 3 ever happens at all. If the instance already exists, you
return it immediately — `__new__` and `__init__` never run.

```python
# What Python does by default (type.__call__):
def __call__(cls, *args, **kwargs):
    obj = cls.__new__(cls, *args, **kwargs)
    if isinstance(obj, cls):
        cls.__init__(obj, *args, **kwargs)
    return obj

# What SingletonMeta.__call__ does instead:
def __call__(cls, *args, **kwargs):
    if cls not in cls._instances:
        obj = super().__call__(*args, **kwargs)  # run the default pipeline ONCE
        cls._instances[cls] = obj
    return cls._instances[cls]               # always return the stored instance
```

---

## 2. The Singleton Pattern

### What It Solves

Some resources are expensive to create and must be shared. A database connection pool
takes time to initialise, has finite connections, and must be consistent across the app.
You want one pool — not one per request, not one per module, not one per thread. One.

### The Analogy

> Your college has one library. Not one per student. One.
>
> The first student to arrive on campus day one found an empty plot of land.
> The faculty (the metaclass) oversaw construction and wrote one rule into the rulebook:
> **"If the library already exists, point students to it. Never build another."**
>
> Every student after that walks in and uses the existing library.
> The rulebook (SingletonMeta) is not the library. It governs the library's creation.
> The library (DatabaseConnectionPool) manages what happens inside — desks, books, connections.

### Full Implementation With Internals Explained

```python
from __future__ import annotations
from typing import Any
import threading


class SingletonMeta(type):
    """
    Metaclass that enforces one instance per class.

    Why a metaclass and not a classmethod or module-level variable?
    Because metaclass.__call__ intercepts construction BEFORE __init__ runs.
    A classmethod approach still calls __init__ on every "call" unless you
    carefully guard it — fragile. Metaclass is the clean, correct mechanism.
    """

    # Stored at the METACLASS level — shared across ALL classes that use this metaclass.
    # Key:   the class itself (e.g. DatabaseConnectionPool)
    # Value: the single instance of that class
    _instances: dict[type, Any] = {}

    # One lock shared across all singleton classes.
    # This is fine because the critical section is tiny (just a dict lookup + assignment).
    _lock: threading.Lock = threading.Lock()

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        # ACQUIRE the lock before checking _instances.
        # Without this: two threads both check, both find nothing, both create an instance.
        # Result: two "singletons". The lock closes this window completely.
        with cls._lock:
            if cls not in cls._instances:
                # super().__call__ runs the normal pipeline:
                # cls.__new__(cls) → cls.__init__(instance)
                # This is the ONE time __init__ will ever run for this class.
                instance = super().__call__(*args, **kwargs)
                cls._instances[cls] = instance

        # Return the stored instance — whether we just created it or it already existed.
        return cls._instances[cls]


class DatabaseConnectionPool(metaclass=SingletonMeta):
    """
    A connection pool with guaranteed single instance.

    NOTE: This uses threading.Lock in SingletonMeta which is fine here because
    the lock is only held during instantiation, which happens once at startup —
    before the async event loop starts processing requests.
    Once created, the pool itself must be async-safe (see Section 5).
    """

    def __init__(self, max_connections: int = 10) -> None:
        # This runs EXACTLY ONCE in the lifetime of the program.
        # If SingletonMeta.__call__ returns the existing instance on the second call,
        # Python never reaches this line again.
        if max_connections <= 0:
            raise ValueError("max_connections must be > 0")
        self.max_connections = max_connections
        self._pool: list[str] = []
        self._initialize_pool()

    def _initialize_pool(self) -> None:
        for i in range(self.max_connections):
            self._pool.append(f"connection_{i}")
```

### What Happens on Second Call

```python
pool_a = DatabaseConnectionPool(max_connections=10)
pool_b = DatabaseConnectionPool(max_connections=99)  # <-- different arg, doesn't matter

print(pool_a is pool_b)          # True — same object
print(pool_b.max_connections)    # 10 — second __init__ never ran
```

This is a known footgun of Singleton. The second set of arguments is silently ignored.
If you need configurable initialisation, use `lifespan` instead (see Section 7).

### The Critical Consequence of `__init__` Running Twice

If the metaclass guard failed and `__init__` ran on every call:

```python
def __init__(self, max_connections: int = 10) -> None:
    self._pool: list[str] = []    # <-- THIS LINE WIPES THE POOL
    self._initialize_pool()
```

Every connection handed out to a live coroutine now points to a slot in an old, reset pool.
The coroutine holds `"connection_3"`. The pool rebuilt itself. `"connection_3"` will be
handed to someone else simultaneously. **Silent double-use of the same connection.**
In a real DB, this means two queries writing to the same socket simultaneously. Data corruption.

---

## 3. Thread Safety in Async

### First, Understand the GIL

CPython has a **Global Interpreter Lock (GIL)** — a mutex that allows only one thread to
execute Python bytecode at a time. Many developers assume this means Python is "thread-safe".

**It is not.** The GIL releases between bytecode instructions — not between your Python
statements. A single `if self._pool: self._pool.pop()` can be interrupted between the
`if` check and the `pop()`. Two threads can both pass the `if`, then both `pop()`.

### The Bigger Problem: Async Is Not Threads

FastAPI uses `asyncio` — a **single-threaded, cooperative concurrency model**. There are
no multiple threads fighting over the GIL. There is **one thread running one event loop**.

The event loop switches between coroutines at `await` points — moments where a coroutine
voluntarily says "I'm waiting for something, go do other work."

This means the race condition is not thread-vs-thread. It is coroutine-vs-coroutine:

```python
# Coroutine A checks the pool at line 1
# Event loop switches to Coroutine B (at an await point elsewhere)
# Coroutine B also checks the pool — same state
# Both proceed. Both try to pop. One crashes.
```

### What `threading.Lock` Does in This Context

`threading.Lock.acquire()` is **blocking** — it tells the OS: "pause this thread until
the lock is free." In a multi-threaded app, this is fine. The OS suspends Thread B and
schedules Thread C on a different CPU core.

In an async app, there is **one thread**. When that one thread blocks, the **entire event
loop freezes**. No other coroutine runs. Every pending request stalls.

```
THREAD: [event loop running] → hits threading.Lock.acquire() → BLOCKED
         └── ALL coroutines frozen. Zero requests processed. CPU idle.
```

At low traffic this is invisible — the lock is held for microseconds. At high traffic with
hundreds of concurrent requests, you get cascading stalls that look like random slowdowns
with no obvious cause. Incredibly hard to debug.

---

## 4. The Async Event Loop

### What It Actually Is

The event loop is a scheduler. It maintains a queue of coroutines ready to run. It runs one
coroutine until that coroutine hits an `await` — then it pauses it and picks the next ready
coroutine. It never runs two coroutines simultaneously.

```
Event Loop Cycle:
1. Pick next ready coroutine from queue
2. Run it until it hits `await` or returns
3. If `await`: suspend it, register a callback for when the awaited thing resolves
4. Go to step 1
```

### The Analogy

> The event loop is a single chef in a restaurant kitchen. He handles 200 orders
> by constantly switching tasks.
>
> "Put the pasta on to boil. While it boils, start the sauce. While sauce simmers,
> plate the salad. Pasta done — drain it. Back to sauce."
>
> He never stops moving. He never waits for the pasta to boil while standing still.
> He schedules and switches. That is `asyncio`.
>
> `threading.Lock` (blocking) tells the chef: "Stand at the walk-in fridge and hold
> the door shut until I get back." He stands there. Every other dish burns.
>
> `asyncio.Lock` is a sticky note on the fridge: "In use — back in 30 seconds."
> The chef goes and works on other dishes. When he checks back and the note is gone,
> he opens the fridge. Nothing burned.

### `asyncio.Lock` — The Correct Tool

```python
import asyncio

lock = asyncio.Lock()

async def safe_operation():
    async with lock:
        # Only one coroutine executes this block at a time.
        # Other coroutines that try to enter will `await` here —
        # yielding control to the event loop, not blocking the thread.
        result = await do_something()
    return result
```

When Coroutine B hits `async with lock` and the lock is held by Coroutine A:
- B is suspended
- Event loop runs Coroutine C, D, E...
- When A releases the lock, B is woken up and put back in the ready queue
- B eventually runs

**The thread never stops.** The event loop never stalls. That is the entire point.

### Comparison Table

| | `threading.Lock` | `asyncio.Lock` |
|---|---|---|
| Correct context | Multi-threaded code | Async / event loop code |
| On contention | Blocks the OS thread | `await`s — yields to event loop |
| Effect on event loop | Freezes everything | No effect — other coroutines run |
| API | `with lock:` | `async with lock:` |
| Can be used in `async def`? | Technically yes — dangerously | Yes — designed for it |

---

## 5. Connection Pools

### What a Connection Pool Is

Opening a database connection is expensive — DNS lookup, TCP handshake, auth negotiation,
session setup. This can take 20–100ms per connection. If your API opens a fresh connection
per request, you burn 100ms of overhead on every single call before any query runs.

A connection pool pre-opens N connections and keeps them warm. Requests borrow a connection,
use it, and return it. Borrowing takes microseconds, not milliseconds.

### Why `list` Fails in Async

```python
# Coroutine A:
if self._pool:           # True — one item left
    # event loop context-switches here (e.g. at an await somewhere else in the call chain)
    # Coroutine B runs the exact same check:
    if self._pool:       # Still True — the item is still there
        conn = self._pool.pop()   # B gets it
    # Back to A:
    conn = self._pool.pop()       # IndexError — empty list
```

The check and the pop are **two separate operations**. The event loop can switch between them.
This is a classic **check-then-act race condition**.

### The Analogy

> Two waiters both glance at the tray and see one clean glass. Both reach for it at the same
> moment. One grabs it. The other's hand closes on air — crash, broken glass.
>
> A proper bar uses a single dispenser with a button. Waiters press the button one at a time.
> The dispenser handles one request atomically. No simultaneous grabs. No crashes.
>
> `asyncio.Queue` is the dispenser.

### `asyncio.Queue` — The Correct Data Structure

```python
import asyncio


queue: asyncio.Queue[str] = asyncio.Queue(maxsize=10)

# Putting items in (non-blocking — only works if space is available)
queue.put_nowait("connection_0")

# Getting items — awaits if empty, never crashes
conn = await queue.get()

# Putting items back
await queue.put(conn)
```

Why it works:

- `queue.get()` is **atomic**. Under the hood it uses an internal lock. No two coroutines
  can simultaneously dequeue the same item.
- If the queue is empty, `await queue.get()` suspends the coroutine and yields to the
  event loop. When an item is put back, the waiting coroutine is woken up automatically.
- No `IndexError`. No `None` checks. No race conditions.

### Production Connection Pool

```python
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator


class DatabaseConnectionPool:
    """
    Async connection pool using asyncio.Queue.

    Design decisions:
    - asyncio.Queue for atomic, blocking-free dequeue
    - @asynccontextmanager for guaranteed release (see Section 6)
    - acquire() is the only public interface — no separate get/release methods
    """

    def __init__(self, name: str, max_connections: int = 10) -> None:
        if max_connections <= 0:
            raise ValueError("max_connections must be > 0")

        self.name = name
        self._max_connections = max_connections

        # maxsize=max_connections means put() will await if pool is full.
        # This prevents returning more connections than we started with.
        self._pool: asyncio.Queue[str] = asyncio.Queue(maxsize=max_connections)

        # put_nowait: non-async version. Safe here because we're in __init__,
        # before any concurrent access is possible.
        for i in range(max_connections):
            self._pool.put_nowait(f"{name}_conn_{i}")

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[str, None]:
        # await queue.get(): suspends if pool is empty, wakes when a conn returns.
        # Never crashes. Never returns None.
        conn = await self._pool.get()
        try:
            yield conn
        finally:
            # finally: runs no matter what — normal exit, exception, or crash.
            # Connection is ALWAYS returned. Leak is structurally impossible.
            await self._pool.put(conn)

    @property
    def available(self) -> int:
        """How many connections are currently idle in the pool."""
        return self._pool.qsize()

    @property
    def in_use(self) -> int:
        """How many connections are currently borrowed."""
        return self._max_connections - self._pool.qsize()
```

---

## 6. Context Managers

### The Problem They Solve

Every time you acquire a resource — a connection, a file, a lock — you must release it.
If release is the caller's responsibility, it will eventually be forgotten. Not by bad
developers. By good developers under pressure, during refactors, in error paths.

```python
conn = await pool.get_connection()
result = await do_work(conn)     # what if this raises an exception?
await pool.release_connection(conn)  # this line never runs on exception
# conn is leaked. Pool loses one slot. Forever.
```

The fix is to make release **impossible to skip** — not by convention, not by code review,
but structurally at the API level.

### How Context Managers Work Internally

A context manager is any object implementing `__enter__` and `__exit__`:

```python
class ManagedResource:
    def __enter__(self):
        # Acquire the resource. Return it.
        return self.resource

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Release the resource.
        # exc_type/val/tb: if an exception occurred, these are set.
        # Return True to suppress the exception. Return False/None to re-raise.
        self.release()
        return False   # don't suppress exceptions
```

The `with` statement calls `__enter__` on entry and `__exit__` on exit —
**even if an exception is raised inside the block**.

For async, the equivalent is `__aenter__` and `__aexit__`, used with `async with`.

### Generator-Based: `@asynccontextmanager`

Writing `__aenter__`/`__aexit__` manually is verbose. `@asynccontextmanager` lets you
write a generator function instead. The `yield` splits setup from teardown:

```python
from contextlib import asynccontextmanager
from typing import AsyncGenerator

@asynccontextmanager
async def acquire(pool) -> AsyncGenerator[str, None]:
    conn = await pool.get()   # setup: everything before yield
    try:
        yield conn            # the caller's `async with` block runs here
    finally:
        await pool.put(conn)  # teardown: always runs, exception or not
```

### Why `finally` Is Guaranteed

`finally` runs even on:
- Normal return from the `with` block
- Any exception raised inside the `with` block
- `return` statement inside the `with` block
- `break` or `continue` in a loop containing the `with` block
- `KeyboardInterrupt` (Ctrl+C)
- `SystemExit`

The only case where `finally` does not run: the Python process is killed with `SIGKILL`
or the power is cut. That is outside the language's control.

### The Analogy

> Old hotel room keys: you take the key, do your work, manually return it to the front desk.
> If you forget, the hotel loses access to that room until someone notices.
>
> Modern hotel keycards: the card deactivates automatically at checkout time.
> You cannot forget to return it. The system enforces the lifecycle.
>
> Context managers are the keycard system.
> `acquire()` is check-in. The `finally` block is the automatic checkout trigger.
> The caller cannot forget.

### The Structural Principle

When you design a resource API, ask:
**"Is it possible for a caller to use this incorrectly?"**

If yes → use a context manager to make the incorrect usage impossible.

Real libraries that follow this:
- `asyncpg`: `pool.acquire()` returns a context manager
- `SQLAlchemy async`: `async_session()` returns a context manager
- `aiofiles`: `aiofiles.open()` returns a context manager
- `httpx.AsyncClient`: used as `async with httpx.AsyncClient() as client:`

---

## 7. Singleton as Antipattern

### The Full Case

Singleton solves a real problem — one shared instance — but creates three new ones.

#### Problem 1: Testing Is Broken

```python
# test_payment.py
def test_process_payment():
    pool = DatabaseConnectionPool()  # returns the GLOBAL instance
    # You cannot replace this with a mock.
    # Even if you try to patch it, the Singleton returns the real one.
    # Tests share state. If test_a uses connections and doesn't release,
    # test_b starts with a drained pool. Order-dependent failures.
    # Tests that pass alone fail in CI. Debugging this is a nightmare.
```

#### Problem 2: Hidden Global State

```python
def process_payment(amount: float) -> bool:
    pool = DatabaseConnectionPool()  # dependency invisible in the signature
    with pool.acquire() as conn:
        ...
```

You cannot tell from the function signature that `process_payment` touches a database.
You cannot tell which database. You cannot tell what happens if it's not initialized.
This function has a **hidden dependency** — the global singleton state.

In large codebases, this means you cannot reason about a function in isolation. You must
trace the entire call tree to understand what state it reads and writes.

#### Problem 3: Tight Coupling — Violates Dependency Inversion

The **Dependency Inversion Principle** says: high-level modules should not depend on
low-level modules directly. Both should depend on abstractions.

Singleton hardcodes the dependency:

```python
class PaymentService:
    def process(self, amount: float):
        pool = DatabaseConnectionPool()   # hardcoded to ONE implementation
        ...
```

You cannot swap `DatabaseConnectionPool` for a Redis pool, an in-memory mock, or a
read-replica pool. Every caller must be changed individually.

#### Problem 4: Multi-Process Deployment

In production, you run FastAPI with multiple worker processes (Gunicorn + Uvicorn workers).
Each process has its own memory. Each process creates its own Singleton instance.

If your Singleton was meant to be shared across the entire application — it isn't.
You now have 4 workers with 4 "singletons" that know nothing about each other.

State stored in the Singleton (e.g. in-memory cache, connection counts) is silently
per-process, not per-application. Silent correctness bugs.

### The Replacement: FastAPI `Depends()` + `app.state` + `lifespan`

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs ONCE at startup — before any request is processed.
    # No concurrent access possible. No lock needed.
    app.state.pool = DatabaseConnectionPool(name="postgres", max_connections=20)
    yield
    # Runs ONCE at shutdown — after all requests are done.
    # Clean up here: drain pool, close connections, flush buffers.


app = FastAPI(lifespan=lifespan)


# Dependency function — this is what gets injected into routes
def get_pool(request: Request) -> DatabaseConnectionPool:
    return request.app.state.pool


@app.get("/data")
async def get_data(pool: DatabaseConnectionPool = Depends(get_pool)):
    async with pool.acquire() as conn:
        return {"conn": conn}
```

In tests:

```python
from fastapi.testclient import TestClient

class MockPool:
    @asynccontextmanager
    async def acquire(self):
        yield "mock_connection"

app.dependency_overrides[get_pool] = lambda: MockPool()
client = TestClient(app)
# Every route that depends on get_pool now gets MockPool instead.
# No Singleton. No patching. Clean.
```

How `dependency_overrides` works: FastAPI's DI system checks this dict before resolving
any dependency. If `get_pool` is a key, it calls the value instead. One line swaps the
entire dependency for every test.

---

## 8. Multi-Pool Architecture in FastAPI

### Why Multiple Pools?

Different databases serve different purposes:
- **PostgreSQL**: persistent storage, complex queries, transactions
- **Redis**: millisecond-latency cache, sessions, pub/sub, rate limiting state

Each needs different connection counts. Redis connections are cheap and fast — you might
want 50. PostgreSQL connections are heavier — 20 might be the limit before the DB strains.

### `PoolRegistry` — A Plain Container

```python
from dataclasses import dataclass


@dataclass
class PoolRegistry:
    """
    A plain data container for multiple pools.
    Not a Singleton. Not a global. Just a dataclass
    that holds references to pre-initialized pools.
    Attached to app.state at startup, gone at shutdown.
    """
    postgres: DatabaseConnectionPool
    redis: DatabaseConnectionPool
```

`@dataclass` auto-generates `__init__`, `__repr__`, `__eq__`. No boilerplate.
The registry itself has no logic — it is just a named container.

### Complete Multi-Pool Setup

```python
from contextlib import asynccontextmanager
from dataclasses import dataclass
from fastapi import Depends, FastAPI, Request


@dataclass
class PoolRegistry:
    postgres: DatabaseConnectionPool
    redis: DatabaseConnectionPool


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pools = PoolRegistry(
        postgres=DatabaseConnectionPool(name="postgres", max_connections=20),
        redis=DatabaseConnectionPool(name="redis", max_connections=50),
    )
    yield
    # In production: gracefully drain both pools here.
    # Wait for in-flight requests to return their connections before shutdown.


app = FastAPI(lifespan=lifespan)


# Separate dependency per pool — routes declare exactly what they need
def get_postgres(request: Request) -> DatabaseConnectionPool:
    return request.app.state.pools.postgres


def get_redis(request: Request) -> DatabaseConnectionPool:
    return request.app.state.pools.redis


# A route that only needs postgres
@app.get("/users")
async def list_users(pg: DatabaseConnectionPool = Depends(get_postgres)):
    async with pg.acquire() as conn:
        return {"conn": conn, "pool": "postgres"}


# A route that needs both
@app.get("/dashboard")
async def dashboard(
    pg: DatabaseConnectionPool = Depends(get_postgres),
    redis: DatabaseConnectionPool = Depends(get_redis),
):
    async with pg.acquire() as pg_conn:
        async with redis.acquire() as redis_conn:
            return {"pg": pg_conn, "redis": redis_conn}
```

### Why `app.state` and Not a Module-Level Variable

```python
# This is a module-level global. Don't do this.
pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = DatabaseConnectionPool(...)
    yield
```

Problems with the global approach:
1. Mutable global state — any code anywhere can reassign `pool = None` and break the app
2. Import order matters — if `pool` is imported before `lifespan` runs, you get `None`
3. Tests cannot isolate this — the global persists across test runs
4. Multiple FastAPI apps in one process (rare but real) share the global unintentionally

`app.state` is scoped to the specific FastAPI instance. It is set at startup, read during
requests via `request.app.state`, and garbage-collected with the app object. Clean lifecycle.

---

## 9. Sliding Window Rate Limiter

### What Rate Limiting Is

Rate limiting caps how many requests a client can make in a time window. Without it:

- A bug in a client loops and hits your API 10,000 times per second
- A malicious actor brute-forces your login endpoint
- A single slow user saturates your connection pool, blocking every other user
- Your database gets hammered and falls over, taking the entire app down

Rate limiting is a **first line of defence** at the API layer.

### Fixed Window vs Sliding Window

**Fixed window** — count resets at a fixed clock boundary (e.g. every minute on the minute):

```
Window: 12:00:00 → 12:01:00 | Limit: 100
Client sends 100 requests at 12:00:59 → allowed (window 1)
Client sends 100 requests at 12:01:01 → allowed (window 2)
Total: 200 requests in 2 seconds. Limit bypassed.
```

This is the **boundary exploit** — by timing requests at the edge of two windows, a client
effectively doubles the limit. For login endpoints, this is a serious security hole.

**Sliding window** — the window is always the last N seconds from the current moment:

```
At 12:01:05, window = 12:00:05 → 12:01:05
Every request in the last 60 seconds is counted.
No fixed boundary. No exploit.
```

### The Algorithm

```
For each incoming request from client IP:

1. Get current timestamp T
2. window_start = T - period_seconds
3. Evict all stored timestamps older than window_start
4. If remaining timestamps count >= max_calls:
   → reject with 429
5. Else:
   → record T
   → allow request
```

The `deque` is perfect here because eviction always happens from the **left** (oldest) end.
`deque.popleft()` is O(1). `list.pop(0)` shifts every element left — O(n). At scale with
high cardinality clients and many timestamps, this difference is measurable.

### The Analogy

> Fixed window: a nightclub with a counter that resets at midnight. Get in 99 people at 11:59,
> then 100 more at 12:00:01. 199 people entered in 2 minutes. The rule was "100 per day"
> but the reset timing was exploited.
>
> Sliding window: a bouncer with a clipboard. For every new arrival he counts: "How many
> people entered in the last 60 minutes from right now?" The window moves with him.
> No boundary. No exploit. Always accurate.

### Production Implementation

```python
from __future__ import annotations
from collections import defaultdict, deque
from collections.abc import Deque
import asyncio
from time import monotonic
from typing import DefaultDict

from fastapi import HTTPException, Request, status


class RateLimiter:
    """
    Per-IP sliding window rate limiter.

    Time complexity: O(k) per request where k = expired timestamps to evict.
    Space complexity: O(n * m) where n = unique IPs, m = max timestamps per IP.

    Limitations:
    - Process-local. Does not work across multiple Gunicorn workers.
    - For distributed rate limiting, replace _requests with Redis using
      a sorted set per IP: ZADD, ZREMRANGEBYSCORE, ZCARD, EXPIRE.
    """

    def __init__(
        self,
        *,
        max_calls: int,
        period_seconds: int,
    ) -> None:
        if max_calls <= 0:
            raise ValueError(f"max_calls must be > 0, got {max_calls}")
        if period_seconds <= 0:
            raise ValueError(f"period_seconds must be > 0, got {period_seconds}")

        self._max_calls = max_calls
        self._period_seconds = period_seconds

        # defaultdict(deque): automatically creates an empty deque for new IPs.
        # No manual key existence checks.
        self._requests: DefaultDict[str, Deque[float]] = defaultdict(deque)

        # asyncio.Lock: yields to event loop on contention. Never blocks the thread.
        self._lock = asyncio.Lock()

    async def __call__(self, request: Request) -> None:
        """
        FastAPI calls this automatically when used as a Depends() dependency.
        Raises HTTPException 429 if the rate limit is exceeded.
        """
        client_ip = self._get_client_ip(request)

        # monotonic(): a clock that only moves forward.
        # time.time() can jump backward when the system clock is adjusted (NTP sync).
        # A backward jump here would make window_start incorrect — allowing bursts.
        # monotonic() is immune to this.
        now = monotonic()

        async with self._lock:
            timestamps = self._requests[client_ip]
            window_start = now - self._period_seconds

            # Evict expired timestamps from the left (oldest end of deque).
            # Each popleft() is O(1). The while loop runs at most max_calls times.
            while timestamps and timestamps[0] <= window_start:
                timestamps.popleft()

            # Memory leak prevention: if a client's deque is now empty,
            # remove the key entirely. Without this, every IP that ever made
            # a request stays in memory forever. On a public API with millions
            # of unique visitors, this OOMs the process slowly.
            if not timestamps and client_ip in self._requests:
                del self._requests[client_ip]
                # defaultdict recreates it on next access — no issue
                timestamps = self._requests[client_ip]

            if len(timestamps) >= self._max_calls:
                # Calculate when the oldest request in the window will expire.
                # That is when the client can make their next request.
                retry_after = max(
                    1,
                    int(timestamps[0] + self._period_seconds - now),
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        f"Rate limit exceeded. "
                        f"Max {self._max_calls} requests per {self._period_seconds}s. "
                        f"Retry after {retry_after}s."
                    ),
                    headers={
                        # RFC 6585: number of seconds to wait before retrying
                        "Retry-After": str(retry_after),
                        # De facto standard headers used by GitHub, Stripe, AWS etc.
                        "X-RateLimit-Limit": str(self._max_calls),
                        "X-RateLimit-Remaining": "0",
                        # Unix timestamp when the current window resets
                        "X-RateLimit-Reset": str(int(now + retry_after)),
                    },
                )

            timestamps.append(now)

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """
        Extract client IP from the request.

        Behind a reverse proxy (nginx, Cloudflare, AWS ALB), the real client IP
        is in the X-Forwarded-For header, NOT request.client.host.
        request.client.host will be the proxy's IP — all clients appear to be
        the same IP and they all share one rate limit bucket. Everyone gets 429.

        Production approach behind a trusted proxy:
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()
            return request.client.host

        WARNING: Only trust X-Forwarded-For if you control the proxy.
        Clients can spoof this header directly if it reaches your app unfiltered.
        """
        if request.client is None:
            # Never bucket unknown IPs together.
            # One bad actor with a None client would exhaust the limit for
            # every other None client simultaneously.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot determine client IP address.",
            )
        return request.client.host
```

### Design Decisions Explained

| Decision | Reason |
|---|---|
| `deque` not `list` | `popleft()` is O(1). `list.pop(0)` is O(n) — shifts every element. |
| `asyncio.Lock` not `threading.Lock` | Never blocks the event loop. Yields on contention. |
| `monotonic()` not `time()` | NTP sync can make `time()` jump backward. `monotonic()` is guaranteed forward-only. |
| `Retry-After` header | RFC 6585. Without it, clients retry immediately, making the overload worse. |
| Memory eviction on empty keys | Without it, every unique IP ever seen stays in RAM forever. OOM on public APIs. |
| Keyword-only args with `*,` | Forces `RateLimiter(max_calls=5, period_seconds=60)`. Self-documenting. Prevents `RateLimiter(5, 60)` which is ambiguous. |
| `ValueError` on bad init | Fail fast. Bad config discovered at startup, not during request handling. |

---

## 10. Mini Project — URL Shortener

### What It Builds

A working URL shortener API. Submit a long URL, get a short code back. Use the short code
to redirect to the original URL. This is a real product — Bitly, TinyURL, and t.co are
all URL shorteners at scale.

This project uses every pattern from this session in a context that actually makes sense.

### Why Each Pattern Is Used Here

| Pattern | Where In This Project | Why It Makes Sense |
|---|---|---|
| `asyncio.Queue` pool | Postgres pool for URL storage | Multiple concurrent shortens need isolated "connections" |
| `asyncio.Queue` pool | Redis pool for fast lookups | Cache hits on redirects should be blazing fast |
| `@asynccontextmanager` | `pool.acquire()` | Every acquire must release — leaks ruin the pool |
| `PoolRegistry` on `app.state` | Startup pool init | No global state, testable, clean lifecycle |
| `Depends()` | Route dependencies | Explicit, readable, overridable in tests |
| `RateLimiter` strict | `POST /shorten` | Abuse prevention — spammers create thousands of URLs |
| `RateLimiter` relaxed | `GET /{code}` | Redirects are high-traffic, legit use is frequent |

### Project Structure

```
url_shortener/
├── main.py           FastAPI app, lifespan, routes
├── pool.py           DatabaseConnectionPool, PoolRegistry
├── rate_limiter.py   RateLimiter
├── storage.py        In-memory URL store (simulates Postgres + Redis)
└── requirements.txt
```

### `requirements.txt`

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
```

### `pool.py`

```python
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncGenerator


class DatabaseConnectionPool:
    """
    Async connection pool backed by asyncio.Queue.

    In a real app, "connections" would be asyncpg Connection objects or
    aioredis client instances. Here they are named strings for clarity.
    The pool mechanics are identical regardless of what is stored inside.
    """

    def __init__(self, name: str, max_connections: int = 10) -> None:
        if max_connections <= 0:
            raise ValueError(f"max_connections must be > 0, got {max_connections}")

        self.name = name
        self._max_connections = max_connections
        self._pool: asyncio.Queue[str] = asyncio.Queue(maxsize=max_connections)

        for i in range(max_connections):
            self._pool.put_nowait(f"{name}_conn_{i}")

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[str, None]:
        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    @property
    def available(self) -> int:
        return self._pool.qsize()

    @property
    def in_use(self) -> int:
        return self._max_connections - self._pool.qsize()


@dataclass
class PoolRegistry:
    postgres: DatabaseConnectionPool
    redis: DatabaseConnectionPool
```

### `storage.py`

```python
from __future__ import annotations
import random
import string
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class URLRecord:
    """Represents one stored URL mapping."""
    code: str
    original_url: str
    created_at: datetime
    click_count: int = 0


class URLStorage:
    """
    In-memory URL store. Simulates a split Postgres + Redis architecture:

    - _db: the source of truth (simulates PostgreSQL)
      Stores full URLRecord objects. Writes happen here on creation.

    - _cache: fast lookup layer (simulates Redis)
      Stores code → original_url for redirect hot path.
      In production: Redis with TTL and LRU eviction.

    Thread-safe for async access because Python dict operations are
    atomic at the CPython bytecode level. In a real async app with
    actual DB calls, you would await the DB/cache clients instead.
    """

    def __init__(self) -> None:
        self._db: dict[str, URLRecord] = {}
        self._cache: dict[str, str] = {}       # code → original_url

    def create(self, original_url: str) -> URLRecord:
        """Store a new URL. Returns the created record."""
        code = self._generate_code()
        record = URLRecord(
            code=code,
            original_url=original_url,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._db[code] = record
        self._cache[code] = original_url       # warm the cache immediately
        return record

    def get_url(self, code: str) -> str | None:
        """
        Fast redirect lookup. Checks cache first (Redis path),
        falls back to DB (Postgres path) on cache miss.
        """
        if code in self._cache:
            return self._cache[code]

        record = self._db.get(code)
        if record:
            self._cache[code] = record.original_url   # re-warm cache
            return record.original_url

        return None

    def record_click(self, code: str) -> None:
        """Increment click count for analytics."""
        if code in self._db:
            self._db[code].click_count += 1

    def get_stats(self, code: str) -> URLRecord | None:
        """Return full record with stats. DB-only (no cache for analytics)."""
        return self._db.get(code)

    def total_urls(self) -> int:
        return len(self._db)

    @staticmethod
    def _generate_code(length: int = 7) -> str:
        """
        Generate a random alphanumeric code.
        7 characters → 62^7 ≈ 3.5 trillion combinations.
        Collision probability is negligible at realistic scale.
        Production: use nanoid or base62-encoded UUID for true uniqueness guarantee.
        """
        alphabet = string.ascii_letters + string.digits
        return "".join(random.choices(alphabet, k=length))
```

### `rate_limiter.py`

```python
from __future__ import annotations
from collections import defaultdict, deque
from collections.abc import Deque
import asyncio
from time import monotonic
from typing import DefaultDict

from fastapi import HTTPException, Request, status


class RateLimiter:
    def __init__(self, *, max_calls: int, period_seconds: int) -> None:
        if max_calls <= 0:
            raise ValueError(f"max_calls must be > 0, got {max_calls}")
        if period_seconds <= 0:
            raise ValueError(f"period_seconds must be > 0, got {period_seconds}")

        self._max_calls = max_calls
        self._period_seconds = period_seconds
        self._requests: DefaultDict[str, Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def __call__(self, request: Request) -> None:
        client_ip = self._get_client_ip(request)
        now = monotonic()

        async with self._lock:
            timestamps = self._requests[client_ip]
            window_start = now - self._period_seconds

            while timestamps and timestamps[0] <= window_start:
                timestamps.popleft()

            if not timestamps and client_ip in self._requests:
                del self._requests[client_ip]
                timestamps = self._requests[client_ip]

            if len(timestamps) >= self._max_calls:
                retry_after = max(1, int(timestamps[0] + self._period_seconds - now))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Retry after {retry_after}s.",
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(self._max_calls),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(now + retry_after)),
                    },
                )

            timestamps.append(now)

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        if request.client is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot determine client IP.",
            )
        return request.client.host
```

### `main.py`

```python
from __future__ import annotations
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl

from pool import DatabaseConnectionPool, PoolRegistry
from rate_limiter import RateLimiter
from storage import URLRecord, URLStorage


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ShortenRequest(BaseModel):
    url: HttpUrl     # Pydantic validates this is a real HTTP(S) URL


class ShortenResponse(BaseModel):
    code: str
    short_url: str
    original_url: str


class StatsResponse(BaseModel):
    code: str
    original_url: str
    click_count: int
    created_at: str


# ---------------------------------------------------------------------------
# Lifespan: startup + shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Everything initialised here runs BEFORE any request is processed.
    # No concurrency. No locks needed.
    app.state.pools = PoolRegistry(
        postgres=DatabaseConnectionPool(name="postgres", max_connections=10),
        redis=DatabaseConnectionPool(name="redis", max_connections=20),
    )
    # Shared in-memory storage — simulates real Postgres + Redis backends
    app.state.storage = URLStorage()
    yield
    # Shutdown: pools and storage go out of scope and are garbage-collected.
    # In production: gracefully drain pools, flush in-flight writes, close sockets.


app = FastAPI(
    title="URL Shortener",
    description=(
        "A URL shortener demonstrating async connection pools, "
        "sliding window rate limiting, and FastAPI dependency injection."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def get_postgres(request: Request) -> DatabaseConnectionPool:
    return request.app.state.pools.postgres


def get_redis(request: Request) -> DatabaseConnectionPool:
    return request.app.state.pools.redis


def get_storage(request: Request) -> URLStorage:
    return request.app.state.storage


# Different limits for different endpoints.
# /shorten: strict — 10 per minute. Prevents URL spam and abuse.
# /redirect: relaxed — 60 per minute. Real users click links frequently.
shorten_limiter = RateLimiter(max_calls=10, period_seconds=60)
redirect_limiter = RateLimiter(max_calls=60, period_seconds=60)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post(
    "/shorten",
    response_model=ShortenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Shorten a URL",
    dependencies=[Depends(shorten_limiter)],
)
async def shorten_url(
    body: ShortenRequest,
    pg: DatabaseConnectionPool = Depends(get_postgres),
    storage: URLStorage = Depends(get_storage),
) -> ShortenResponse:
    """
    Accept a long URL and return a short code.

    Uses the Postgres pool for the write operation.
    Rate limited: 10 requests per minute per IP.
    """
    async with pg.acquire() as _conn:
        # _conn is the "database connection" — in a real app you would
        # await _conn.execute("INSERT INTO urls ...") here.
        # Here we write to in-memory storage instead.
        record: URLRecord = storage.create(str(body.url))

    return ShortenResponse(
        code=record.code,
        short_url=f"http://localhost:8000/{record.code}",
        original_url=record.original_url,
    )


@app.get(
    "/{code}",
    summary="Redirect to original URL",
    dependencies=[Depends(redirect_limiter)],
    responses={
        302: {"description": "Redirect to original URL"},
        404: {"description": "Short code not found"},
    },
)
async def redirect(
    code: str,
    redis: DatabaseConnectionPool = Depends(get_redis),
    pg: DatabaseConnectionPool = Depends(get_postgres),
    storage: URLStorage = Depends(get_storage),
) -> RedirectResponse:
    """
    Redirect a short code to its original URL.

    Checks Redis cache first (fast path).
    Falls back to Postgres on cache miss (slow path).
    Records a click for analytics.
    Rate limited: 60 requests per minute per IP.
    """
    # Fast path: cache lookup via Redis pool
    async with redis.acquire() as _cache_conn:
        original_url = storage.get_url(code)

    if original_url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Short code '{code}' not found.",
        )

    # Record the click via Postgres pool (analytics write)
    async with pg.acquire() as _pg_conn:
        storage.record_click(code)

    # 302 Found: temporary redirect. Browser does not cache this.
    # Use 301 only if the mapping is permanent and you never want to change it.
    return RedirectResponse(url=original_url, status_code=302)


@app.get(
    "/stats/{code}",
    response_model=StatsResponse,
    summary="Get click stats for a short code",
)
async def get_stats(
    code: str,
    pg: DatabaseConnectionPool = Depends(get_postgres),
    storage: URLStorage = Depends(get_storage),
) -> StatsResponse:
    """
    Return analytics for a short code: click count, creation time, original URL.
    No rate limit — stats are read-only and low-traffic.
    """
    async with pg.acquire() as _conn:
        record = storage.get_stats(code)

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Short code '{code}' not found.",
        )

    return StatsResponse(
        code=record.code,
        original_url=record.original_url,
        click_count=record.click_count,
        created_at=record.created_at.isoformat(),
    )


@app.get(
    "/health",
    summary="Health check with pool status",
)
async def health(
    pg: DatabaseConnectionPool = Depends(get_postgres),
    redis: DatabaseConnectionPool = Depends(get_redis),
    storage: URLStorage = Depends(get_storage),
) -> dict:
    return {
        "status": "ok",
        "postgres": {
            "available": pg.available,
            "in_use": pg.in_use,
        },
        "redis": {
            "available": redis.available,
            "in_use": redis.in_use,
        },
        "total_urls_stored": storage.total_urls(),
    }
```

### How to Run

```bash
# 1. Install dependencies
pip install fastapi uvicorn

# 2. From the url_shortener/ directory
uvicorn main:app --reload

# 3. Open Swagger UI
# http://localhost:8000/docs
```

### Example API Calls

```bash
# Shorten a URL
curl -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.anthropic.com/research/claude"}'

# Response:
# {
#   "code": "aB3xY7z",
#   "short_url": "http://localhost:8000/aB3xY7z",
#   "original_url": "https://www.anthropic.com/research/claude"
# }

# Redirect (browser will follow the 302)
curl -L http://localhost:8000/aB3xY7z

# Get stats
curl http://localhost:8000/stats/aB3xY7z

# Health check
curl http://localhost:8000/health

# Test rate limiting (run 11 times — 11th should return 429)
for i in {1..11}; do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/shorten \
    -H "Content-Type: application/json" \
    -d '{"url": "https://example.com"}'
done
```

### What Happens When the Pool Is Exhausted

If all 10 Postgres connections are in use and a new request comes in:

```python
async with pg.acquire() as conn:
    # This line awaits if pool is empty.
    # The coroutine suspends. Other requests continue.
    # When another request's context manager exits, a connection returns.
    # This coroutine wakes up and proceeds.
    ...
```

No error. No crash. No `None`. The request waits its turn politely.
You can observe this with `/health` — watch `in_use` climb under load.

---

## 11. Theoretical Q&A

### Q1 (Easy) — Why does `__init__` only run once in a Singleton?

`SingletonMeta.__call__` checks `cls._instances` before calling `super().__call__()`.
`super().__call__()` is the only code path that triggers `__init__`. On the second call,
the instance already exists in `_instances` — the method returns it directly, and
`super().__call__()` is never reached. `__init__` never fires.

If `__init__` ran every time: `self._pool = []` would wipe the pool on every call.
Every client holding a connection would have a dangling reference. Two clients could
hold the "same" connection simultaneously. Data corruption in the underlying DB.

---

### Q2 (Medium) — Why is `threading.Lock` dangerous in async FastAPI?

FastAPI uses a single-threaded event loop. `threading.Lock.acquire()` is an OS-level
blocking call — it suspends the OS thread until the lock is free. In an async app
there is only one thread. Suspending it freezes the event loop entirely. Every pending
coroutine stalls. Not just the waiting one — all of them.

`asyncio.Lock` uses `await` on contention — the coroutine yields back to the event loop.
Other coroutines continue running. The thread never stops.

---

### Q3 (Intermediate) — Why is `list` wrong for an async connection pool?

`list.pop()` is two operations in Python's execution model: check, then pop.
The event loop can switch coroutines between these steps. Two coroutines both pass the
check, both call pop. One gets the connection. The other gets `IndexError`.

`asyncio.Queue.get()` is atomic — it is a single awaitable operation protected by an
internal lock. No two coroutines can dequeue the same item. If empty, it awaits
automatically — no crash, no `None`.

---

### Q4 (Expert) — What if a coroutine crashes before releasing a connection?

The connection is permanently removed from the pool. No exception propagates about the
pool itself. Over time, crashes accumulate and drain the pool. All new requests await
on `pool.acquire()` forever — the API appears to hang with no error log for the pool.

Fix: `@asynccontextmanager` with `try/finally`. `finally` is guaranteed to run on
normal exit, any exception, `return`, `break`, `KeyboardInterrupt`, and `SystemExit`.
The connection is returned to the pool before the exception propagates upward.
Callers cannot bypass this — `acquire()` is the only API surface. Leak is impossible.

---

### Q5 (Hard) — Why is Singleton an antipattern in production APIs?

Three reasons.

Testing: the global instance cannot be swapped for a mock. Tests share state. Test order
affects results. CI passes locally, fails in pipeline.

Hidden global state: dependencies are invisible in function signatures. Any code can
access the Singleton silently. Debugging requires tracing the entire codebase.

Tight coupling: violates Dependency Inversion. The class is hardcoded to one concrete
implementation. Swapping backends or adding read replicas requires touching every caller.

Bonus: in multi-process deployments (Gunicorn workers), each process has its own memory.
Each creates its own "singleton." State is per-process, not per-application.

Replace with: `app.state` + `lifespan` + `Depends()`. Explicit, testable, swappable,
correctly scoped to the application lifecycle.

---

### Q6 (Complex) — How do you architect multiple pools cleanly in FastAPI?

`PoolRegistry` dataclass holds both pools — a plain named container, not a Singleton.
Both pools are initialized in `lifespan` with independent `max_connections` configs,
attached to `app.state.pools` which is scoped to the FastAPI instance's lifecycle.

Separate dependency functions (`get_postgres`, `get_redis`) read from `app.state.pools`.
Routes declare exactly which pool they need via `Depends()` — dependencies are visible
in the function signature, explicit, and readable.

Tests override either dependency independently via `app.dependency_overrides`.
Shutdown is handled in one place — the `lifespan` context manager's post-yield block.
No global variables. No Singleton. No hidden state.

---

## 12. Quick Reference

### When to Use What

| Situation | Use |
|---|---|
| Need one shared resource across the app | `app.state` + `lifespan` |
| Lock in async / event loop code | `asyncio.Lock` |
| Lock in threaded (non-async) code | `threading.Lock` |
| Pool of reusable resources, async | `asyncio.Queue` |
| Guaranteed resource cleanup | `@asynccontextmanager` with `try/finally` |
| Inject dependencies into routes | `Depends()` |
| Rate limit per client | Sliding window with `deque` + `asyncio.Lock` |
| Timestamps in rate limiting | `time.monotonic()` not `time.time()` |
| Store pool and storage for app lifecycle | `app.state` |
| Multiple pools with separate configs | `PoolRegistry` dataclass |

### The Production Checklist

Before shipping any async Python backend:

- [ ] All locks are `asyncio.Lock`, not `threading.Lock`
- [ ] Connection pools use `asyncio.Queue`, not `list`
- [ ] Every resource acquisition is wrapped in a `@asynccontextmanager`
- [ ] No Singleton patterns — use `app.state` + `Depends()`
- [ ] Rate limiters use `monotonic()` for timestamps
- [ ] Rate limiter memory is cleaned up (empty keys deleted)
- [ ] `Retry-After` header is set on 429 responses
- [ ] `__init__` fails fast on invalid config (`ValueError`, not silent defaults)
- [ ] No hardcoded secrets — use environment variables
- [ ] Startup/shutdown logic lives in `lifespan`, not module-level code

---

*Every pattern in this document is used in production Python backends at companies like
Stripe, GitHub, Notion, and Linear. The implementations here are simplified for learning —
the mechanics and reasoning are identical to what runs in real systems.*
