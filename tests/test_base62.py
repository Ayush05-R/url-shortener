import pytest

from app.algorithms.base62 import decode, encode


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        (0, "0"),
        (1, "1"),
        (10, "a"),
        (61, "Z"),
        (62, "10"),
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
        ("0", 0),
        ("1", 1),
        ("a", 10),
        ("Z", 61),
        ("10", 62),
        ("21", 125),
    ],
)
def test_decode_known_values(encoded: str, expected: int) -> None:
    assert decode(encoded) == expected


@pytest.mark.parametrize(
    "value",
    [
        0,
        1,
        10,
        61,
        62,
        125,
        1_000,
        1_000_000,
        999_999_999,
    ],
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
