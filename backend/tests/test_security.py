import pytest

from app.core.security import UnsafeUrlError, validate_public_http_url


@pytest.mark.parametrize("url", ["http://127.0.0.1", "http://localhost:8000", "ftp://example.com"])
def test_unsafe_or_invalid_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_http_url(url)
