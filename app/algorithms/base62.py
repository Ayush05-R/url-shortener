__all__ = ["encode", "decode"]

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)  # 62
_CHAR_TO_INDEX: dict[str, int] = {char: idx for idx, char in enumerate(ALPHABET)}


def encode(n: int) -> str:
    """Convert a positive integer to a base62 string."""
    if n < 0:
        raise ValueError("Input must be a non-negative integer.")
    if n == 0:
        return ALPHABET[0]
    chars: list[str] = []  # The list of characters that will form the base62 string
    while n > 0:
        n, remainder = divmod(n, BASE)  # Get the quotient and remainder
        chars.append(
            ALPHABET[remainder]
        )  # Append the corresponding character to the list
    return "".join(
        reversed(chars)
    )  # Reverse the list and join to form the final string


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
