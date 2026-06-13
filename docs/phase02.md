# Phase 2 — Base62 Algorithm
### URL Shortener Build Log

> This document explains everything built in Phase 2 — number systems, the encoding
> and decoding algorithms, O(1) vs O(n) complexity, parametrized testing, and every
> design decision made. Read this before touching Phase 3.

---

## Table of Contents

1. [What Phase 2 Builds](#1-what-phase-2-builds)
2. [Why Base62 — The Problem It Solves](#2-why-base62)
3. [Number Systems From Scratch](#3-number-systems-from-scratch)
4. [The Encoding Algorithm](#4-the-encoding-algorithm)
5. [The Decoding Algorithm](#5-the-decoding-algorithm)
6. [O(n) vs O(1) — The Lookup Optimisation](#6-on-vs-o1)
7. [Edge Cases — Why They Matter](#7-edge-cases)
8. [Module Design — `__all__` and Private Constants](#8-module-design)
9. [Testing — `@pytest.mark.parametrize`](#9-testing-parametrize)
10. [The Final Implementation](#10-the-final-implementation)
11. [The Final Tests](#11-the-final-tests)
12. [What Phase 2 Does NOT Have Yet](#12-what-phase-2-does-not-have-yet)
13. [Phase 3 Preview](#13-phase-3-preview)

---

## 1. What Phase 2 Builds

One file: `app/algorithms/base62.py`
One test file: `tests/test_base62.py`
26 passing tests.

Zero FastAPI. Zero database. Zero configuration. Pure Python.

This is the DSA core of the entire URL shortener. Every short code like `aB3xY7z`
that the app generates comes out of this file. The algorithm is simple, fast, and
completely deterministic — given the same integer, it always produces the same code.

---

## 2. Why Base62 — The Problem It Solves

### The Naive Approach: Random Strings

The obvious way to generate short codes is to pick random characters:

```python
import random, string
code = "".join(random.choices(string.ascii_letters + string.digits, k=7))
```

Problems:
- **Collisions** — two URLs might get the same code. You must check the database
  on every insert to verify uniqueness. At high volume this is a bottleneck.
- **No structure** — the code carries zero information. You cannot reverse it.
- **Unpredictable length** — no guarantee about code length relative to volume.

### The Base62 Approach: Encode the Database ID

Instead of random strings, use the database's **auto-incrementing integer ID**.
Every row in a database table gets a unique integer: 1, 2, 3, 4...

Encode that integer to base62:

```
ID 1       → "1"
ID 62      → "10"
ID 1000    → "g8"
ID 1000000 → "4c92"
```

Benefits:
- **Zero collision** — database IDs are unique by definition. No collision check needed.
- **Reversible** — decode `"4c92"` back to `1000000` anytime without a DB lookup.
- **Short** — base62 produces the shortest URL-safe strings possible.
- **Ordered** — higher IDs produce longer codes predictably.

### Why 62 Specifically

A short URL can only contain URL-safe characters — no `/`, `?`, `#`, `&`, `=` or
spaces. What remains:

```
0-9  →  10 characters
a-z  →  26 characters
A-Z  →  26 characters
─────────────────────
     =  62 characters total
```

62 is the maximum base you can use with alphanumeric characters. Bigger base =
more symbols per position = shorter strings for the same number.

```
ID 3,500,000,000  →  base10:  "3500000000"  (10 chars)
ID 3,500,000,000  →  base62:  "3gRPGi"      (6 chars)
```

---

## 3. Number Systems From Scratch

### What a Base Is

A base (or radix) defines how many unique symbols a number system uses before
it "wraps around" and adds a new position.

```
Base 10 (decimal):   symbols 0-9      wraps at 10
Base 2  (binary):    symbols 0-1      wraps at 2
Base 16 (hex):       symbols 0-9,a-f  wraps at 16
Base 62:             symbols 0-9,a-z,A-Z  wraps at 62
```

### How Positional Value Works

In base 10, the number 425 means:

```
4 × 10² + 2 × 10¹ + 5 × 10⁰
= 4 × 100 + 2 × 10 + 5 × 1
= 400 + 20 + 5
= 425
```

In base 62, the string "6Z" means:

```
6 × 62¹ + 61 × 62⁰       (Z = index 61 in the alphabet)
= 6 × 62 + 61 × 1
= 372 + 61
= 433
```

Verify: `encode(433)` should return `"6Z"`.

### The Alphabet

```python
ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
```

Position in this string is the "digit value":

```
ALPHABET[0]  = "0"  → value 0
ALPHABET[9]  = "9"  → value 9
ALPHABET[10] = "a"  → value 10
ALPHABET[35] = "z"  → value 35
ALPHABET[36] = "A"  → value 36
ALPHABET[61] = "Z"  → value 61
```

This ordering (digits first, then lowercase, then uppercase) is a convention.
What matters is consistency — encode and decode must use the same alphabet order.

---

## 4. The Encoding Algorithm

### The Concept: Repeated Division

To convert integer `n` to any base, repeatedly divide by the base and collect
remainders. The remainders, read in reverse order, form the encoded string.

### Step-by-Step: encode(125)

```
n = 125, BASE = 62

Iteration 1:
    125 ÷ 62 = 2 remainder 1
    n = 2, remainder = 1
    ALPHABET[1] = "1" → collect "1"

Iteration 2:
    2 ÷ 62 = 0 remainder 2
    n = 0, remainder = 2
    ALPHABET[2] = "2" → collect "2"

n = 0, stop.

Collected (in order): ["1", "2"]
Reversed:             ["2", "1"]
Joined:               "21"
```

Verify: `2 × 62 + 1 = 125` ✓

### Why Reversed?

The first remainder is the **least significant digit** (rightmost position).
The last remainder is the **most significant digit** (leftmost position).
Reversing puts the most significant digit first — same convention as all
number systems you already know.

### `divmod` — The Right Tool

Python's built-in `divmod(a, b)` returns `(quotient, remainder)` in one call:

```python
divmod(125, 62)  # returns (2, 1)
# same as:
# quotient  = 125 // 62  = 2
# remainder = 125 % 62   = 1
```

Using `divmod` is cleaner and slightly faster than two separate operations.

### The Implementation

```python
def encode(n: int) -> str:
    """Convert a non-negative integer to a base62 string."""
    if n < 0:
        raise ValueError("Input must be a non-negative integer.")
    if n == 0:
        return ALPHABET[0]   # "0" — handle zero explicitly

    chars: list[str] = []
    while n > 0:
        n, remainder = divmod(n, BASE)
        chars.append(ALPHABET[remainder])

    return "".join(reversed(chars))
```

### Why Zero Is a Special Case

If `n = 0`, the `while n > 0` loop never executes. `chars` stays empty.
`"".join(reversed([]))` returns `""` — an empty string. That is wrong.
`encode(0)` must return `"0"`.

The explicit guard `if n == 0: return ALPHABET[0]` handles this before the loop.

---

## 5. The Decoding Algorithm

### The Concept: Horner's Method

Decoding is the reverse — convert each character back to its digit value and
reconstruct the integer using positional arithmetic.

```
result = 0
for each character left-to-right:
    result = result × BASE + digit_value
```

This is **Horner's method** — an efficient way to evaluate a polynomial that
avoids computing powers like `62²`, `62³` etc.

### Step-by-Step: decode("21")

```
s = "21"

Start: result = 0

Character "2": digit = 2
    result = 0 × 62 + 2 = 2

Character "1": digit = 1
    result = 2 × 62 + 1 = 125

Return 125
```

Verify: `encode(125) = "21"` ✓

### The Implementation

```python
def decode(s: str) -> int:
    """Convert a base62 string back to an integer."""
    if not s:
        raise ValueError("Input string must not be empty.")
    value = 0
    for char in s:
        if char not in _CHAR_TO_INDEX:
            raise ValueError(f"Invalid base62 character: {char!r}")
        value = value * BASE + _CHAR_TO_INDEX[char]
    return value
```

---

## 6. O(n) vs O(1) — The Lookup Optimisation

### The Problem with `ALPHABET.index(char)`

The first version of `decode` used:

```python
digit = ALPHABET.index(char)
```

`str.index()` is a **linear scan** — it starts at position 0 and checks each
character until it finds a match. On average it scans half the string.

For a 62-character alphabet, that is up to 62 comparisons per character.

**Time complexity: O(n)** where n = length of alphabet (62).

For one decode call, this is invisible. For a URL shortener doing millions of
redirects per day — every single redirect decodes a short code — it adds up.

### The Fix: Pre-Built Dictionary

```python
_CHAR_TO_INDEX: dict[str, int] = {char: idx for idx, char in enumerate(ALPHABET)}
```

This creates a dictionary at **module load time** (once, when Python imports the file):

```
{
    "0": 0,
    "1": 1,
    ...
    "9": 9,
    "a": 10,
    ...
    "Z": 61,
}
```

Now `_CHAR_TO_INDEX[char]` is a **hash map lookup** — O(1) regardless of alphabet size.

**Time complexity: O(1).**

### The Analogy

> `ALPHABET.index(char)` is like finding a word in a dictionary by reading every
> page from the start until you find it. Correct — but slow.
>
> `_CHAR_TO_INDEX[char]` is like using the dictionary's index at the back. You go
> directly to the right page. One step, regardless of dictionary size.

### The Underscore Prefix — `_CHAR_TO_INDEX`

The leading underscore is a Python convention meaning **"internal implementation detail."**
It signals to other developers: "don't import this directly — it's not part of the
public API." It is not enforced by Python, but it is universally respected.

```python
# Other files should use:
from app.algorithms.base62 import encode, decode

# Not this:
from app.algorithms.base62 import _CHAR_TO_INDEX   # discouraged
```

---

## 7. Edge Cases — Why They Matter

An algorithm is only as good as how it handles unexpected input. Every function
you write should be asked: **what happens on bad input?**

### Edge Cases in `encode`

| Input | Expected Behaviour | Why |
|---|---|---|
| `0` | `"0"` | Loop never runs — explicit guard needed |
| Negative number | `ValueError` | Negative IDs don't exist in a database |
| Very large number | Short string | Should just work — Python ints are arbitrary precision |

### Edge Cases in `decode`

| Input | Expected Behaviour | Why |
|---|---|---|
| `""` (empty) | `ValueError` | Ambiguous — same result as `decode("0")` without guard |
| `"!!!"` (invalid chars) | `ValueError` | Not a valid base62 string |
| `"0"` | `0` | Valid — the zero case |

### Why `raise ValueError` — Not `return None`

```python
# Bad
def encode(n: int) -> str | None:
    if n < 0:
        return None

# Good
def encode(n: int) -> str:
    if n < 0:
        raise ValueError("Input must be a non-negative integer.")
```

Returning `None` on bad input forces every caller to check the return value:

```python
code = encode(-1)
if code is None:    # easy to forget this check
    handle_error()
use(code)           # silently proceeds with None if check is skipped
```

Raising `ValueError` crashes immediately at the source of the problem — not
silently later when `None` reaches a place that expects a string.

**Fail fast. Make bugs loud.**

---

## 8. Module Design

### `__all__` — Declaring the Public API

```python
__all__ = ["encode", "decode"]
```

`__all__` is a list of names that are exported when someone does
`from app.algorithms.base62 import *`.

More importantly, it is a **declaration of intent** — it tells any developer
reading this file: "the public interface of this module is `encode` and `decode`.
Everything else is internal."

IDE tools, linters, and documentation generators all respect `__all__`.

### Module Layout Convention

```python
# 1. Constants (public)
ALPHABET = "..."
BASE = len(ALPHABET)

# 2. Public API declaration
__all__ = ["encode", "decode"]

# 3. Internal implementation details (private)
_CHAR_TO_INDEX: dict[str, int] = {char: idx for idx, char in enumerate(ALPHABET)}

# 4. Public functions
def encode(n: int) -> str:
    ...

def decode(s: str) -> int:
    ...
```

This ordering is not enforced by Python but is a widely followed convention.
Constants first, then what's public, then internals, then the actual functions.

---

## 9. Testing — `@pytest.mark.parametrize`

### What It Is

`@pytest.mark.parametrize` runs one test function multiple times with different
inputs. Without it, testing 6 known values requires 6 separate test functions:

```python
# Bad — repetitive
def test_encode_zero():
    assert encode(0) == "0"

def test_encode_one():
    assert encode(1) == "1"

def test_encode_ten():
    assert encode(10) == "a"

# ... 3 more functions
```

With `parametrize`:

```python
# Good — one function, 6 test cases
@pytest.mark.parametrize(
    ("number", "expected"),
    [
        (0,   "0"),
        (1,   "1"),
        (10,  "a"),
        (61,  "Z"),
        (62,  "10"),
        (125, "21"),
    ],
)
def test_encode_known_values(number: int, expected: str) -> None:
    assert encode(number) == expected
```

pytest runs this function once for each tuple in the list, substituting `number`
and `expected` with the values from that tuple. In the output you see:

```
test_encode_known_values[0-0]     PASSED
test_encode_known_values[1-1]     PASSED
test_encode_known_values[10-a]    PASSED
test_encode_known_values[61-Z]    PASSED
test_encode_known_values[62-10]   PASSED
test_encode_known_values[125-21]  PASSED
```

Each case is individually tracked — a failure in one case doesn't skip the others.

### When to Use Parametrize vs Separate Tests

Use `parametrize` when testing the **same logic** with different input/output pairs.
Use separate test functions when each test case has **different setup or assertions**.

```python
# Same logic, different data → parametrize
@pytest.mark.parametrize("value", [0, 1, 62, 125, 1_000_000])
def test_roundtrip(value: int) -> None:
    assert decode(encode(value)) == value

# Different behaviour → separate functions
def test_encode_negative_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        encode(-1)

def test_decode_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        decode("")
```

### `pytest.raises(ValueError, match="...")`

The `match` parameter checks that the exception message contains the given substring:

```python
with pytest.raises(ValueError, match="non-negative"):
    encode(-1)
```

This test passes only if:
1. `encode(-1)` raises `ValueError` AND
2. The error message contains `"non-negative"`

Without `match`, the test passes on any `ValueError` — even one from an
unrelated bug. `match` makes the test specific and meaningful.

### The Roundtrip Test — The Most Important Test

```python
@pytest.mark.parametrize("value", [0, 1, 10, 61, 62, 125, 1_000, 1_000_000, 999_999_999])
def test_roundtrip(value: int) -> None:
    assert decode(encode(value)) == value
```

This single test verifies the fundamental contract: **encode and decode are inverses**.
No matter what integer you start with, `decode(encode(n)) == n` must always hold.
If either function has a bug, this test catches it.

---

## 10. The Final Implementation

```python
# app/algorithms/base62.py

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)  # 62

__all__ = ["encode", "decode"]

# Pre-built O(1) lookup: character → its index in ALPHABET
# Built once at module load time. Never rebuilt.
_CHAR_TO_INDEX: dict[str, int] = {char: idx for idx, char in enumerate(ALPHABET)}


def encode(n: int) -> str:
    """
    Convert a non-negative integer to a base62 string.

    Args:
        n: A non-negative integer (typically a database row ID).

    Returns:
        A base62 encoded string. encode(0) returns "0".

    Raises:
        ValueError: If n is negative.
    """
    if n < 0:
        raise ValueError("Input must be a non-negative integer.")
    if n == 0:
        return ALPHABET[0]

    chars: list[str] = []
    while n > 0:
        n, remainder = divmod(n, BASE)
        chars.append(ALPHABET[remainder])

    return "".join(reversed(chars))


def decode(s: str) -> int:
    """
    Convert a base62 string back to an integer.

    Args:
        s: A non-empty base62 encoded string.

    Returns:
        The integer that was originally encoded.

    Raises:
        ValueError: If s is empty or contains characters not in ALPHABET.
    """
    if not s:
        raise ValueError("Input string must not be empty.")

    value = 0
    for char in s:
        if char not in _CHAR_TO_INDEX:
            raise ValueError(f"Invalid base62 character: {char!r}")
        value = value * BASE + _CHAR_TO_INDEX[char]

    return value
```

---

## 11. The Final Tests

```python
# tests/test_base62.py

import pytest
from app.algorithms.base62 import decode, encode


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        (0,   "0"),
        (1,   "1"),
        (10,  "a"),
        (61,  "Z"),
        (62,  "10"),
        (125, "21"),
    ],
)
def test_encode_known_values(number: int, expected: str) -> None:
    assert encode(number) == expected


def test_encode_zero() -> None:
    assert encode(0) == "0"


def test_encode_large_number() -> None:
    result = encode(1_000_000)
    assert isinstance(result, str)
    assert len(result) < len(str(1_000_000))


@pytest.mark.parametrize(
    ("encoded", "expected"),
    [
        ("0",  0),
        ("1",  1),
        ("a",  10),
        ("Z",  61),
        ("10", 62),
        ("21", 125),
    ],
)
def test_decode_known_values(encoded: str, expected: int) -> None:
    assert decode(encoded) == expected


@pytest.mark.parametrize(
    "value",
    [0, 1, 10, 61, 62, 125, 1_000, 1_000_000, 999_999_999],
)
def test_roundtrip(value: int) -> None:
    assert decode(encode(value)) == value


def test_encode_negative_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        encode(-1)


def test_decode_invalid_char_raises() -> None:
    with pytest.raises(ValueError, match="Invalid base62 character"):
        decode("!!!")


def test_decode_empty_string_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        decode("")
```

---

## 12. What Phase 2 Does NOT Have Yet

- **No database integration** — Base62 encodes integers. Where those integers come
  from (the database auto-increment ID) is wired up in Phase 6.
- **No collision handling** — unnecessary. The uniqueness guarantee comes from the
  database ID, not from the encoding.
- **No URL generation** — `encode(id)` gives a code. Building the full short URL
  (`http://localhost:8000/aB3xY7z`) happens in the service layer, Phase 4.

---

## 13. Phase 3 Preview

Phase 3 builds the **domain layer** — the core of the application's business logic.

Three things get built:

**1. `URLRecord` — the domain model**
A dataclass representing one stored URL. Fields: `id`, `code`, `original_url`,
`created_at`, `click_count`. No database columns, no HTTP concerns. Pure data.

**2. `URLRepository` — the abstract interface**
An abstract base class defining what operations the app needs:
`create`, `get_by_code`, `increment_clicks`, `get_stats`. This is a contract —
any concrete implementation (Postgres, Redis, in-memory) must fulfill it.

**3. `InMemoryURLRepository` — the concrete implementation**
A dict-based implementation of `URLRepository`. No database. Used in tests and
local development. When Phase 6 adds Postgres, it just implements the same interface.

**The key concept in Phase 3:** the Repository Pattern. Routes and services never
touch the database directly. They talk to the repository interface. The concrete
implementation — in-memory now, Postgres later — is swapped without changing a
single line of business logic.

**Best practice for Phase 3:**
Write the abstract interface first. Then write tests against it using the
in-memory implementation. If the tests pass with in-memory, they will pass with
Postgres too — the interface contract guarantees it.

---

*Phase 2 complete. 26 tests passing. The DSA core of the project is done.*
*Every short code generated by this app comes from these two functions.*
