"""Validation helpers for URLs used by server-side downloads."""

import ipaddress
import socket
from urllib.parse import urlparse


ALLOWED_SCHEMES = {"http", "https"}


def is_safe_ip(value: str) -> bool:
    """Return whether an IP address is publicly routable enough to fetch."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False

    return not any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def validate_url(url: str) -> bool:
    """Validate a URL before making a server-side request.

    Hostnames are resolved here and every returned IPv4/IPv6 address must be
    publicly routable. Redirects are deliberately handled by the caller, so a
    redirect cannot silently bypass this validation.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ALLOWED_SCHEMES or not parsed.hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False

        hostname = parsed.hostname
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            return is_safe_ip(hostname)

        addresses = socket.getaddrinfo(
            hostname,
            parsed.port,
            type=socket.SOCK_STREAM,
        )
        if not addresses:
            return False
        return all(is_safe_ip(address[4][0]) for address in addresses)
    except (OSError, ValueError, TypeError):
        return False
