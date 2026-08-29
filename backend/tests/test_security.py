import pytest

from app.core.security import UnsafeUrlError, validate_public_http_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://0.0.0.0",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]",
        "http://localhost:8000",
        "http://service.local",
        "http://user:password@example.com",
        "ftp://example.com",
        "file:///etc/passwd",
    ],
)
def test_unsafe_or_invalid_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_http_url(url)
