# Custom exception hierarchy

class URLShortenerError(Exception):
    """Base exception for all application errors."""
    pass

class URLNotFoundError(URLShortenerError):
    """Raised when a short code does not exist."""
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Short code '{code}' not found.")

class URLExpiredError(URLShortenerError):
    """Raised when a short code exists but has expired."""
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Short code '{code}' has expired.")

class InvalidURLError(URLShortenerError):
    """Raised when the submitted URL is malformed or not allowed."""
    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        super().__init__(f"Invalid URL '{url}': {reason}")
