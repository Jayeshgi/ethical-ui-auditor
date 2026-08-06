from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """Raised when a scan target could reach a local or private network."""


def validate_public_http_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError("A scan URL must be a complete http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URLs containing credentials are not supported.")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise UnsafeUrlError("Local hostnames cannot be scanned.")

    try:
        addresses = {result[4][0] for result in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as error:
        raise UnsafeUrlError("The target hostname could not be resolved.") from error

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            raise UnsafeUrlError("Private, local, reserved, and loopback addresses cannot be scanned.")
    return parsed.geturl()

