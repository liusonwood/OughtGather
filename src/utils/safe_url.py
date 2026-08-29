"""Validation helpers for URLs used by server-side downloads."""

import ipaddress
import socket
from typing import List, Optional, Union
from urllib.parse import urlparse


ALLOWED_SCHEMES = {"http", "https"}

# Additional blocked IPv4/IPv6 networks not fully covered by is_private/is_reserved in older python specs
EXTRA_BLOCKED_NETWORKS = [
    ipaddress.ip_network("100.64.0.0/10"),      # Carrier-grade NAT (RFC 6598)
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1 (RFC 5737)
    ipaddress.ip_network("198.18.0.0/15"),      # Benchmarking (RFC 2544)
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2 (RFC 5737)
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3 (RFC 5737)
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved for future use (RFC 1112)
    ipaddress.ip_network("255.255.255.255/32"), # Limited broadcast
    ipaddress.ip_network("2001:db8::/32"),      # Documentation IPv6
    ipaddress.ip_network("fc00::/7"),           # Unique Local IPv6 (ULA)
]


def is_safe_ip(value: Union[str, ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
    """Return whether an IP address is publicly routable and safe to fetch.

    Blocks:
    - Loopback (127.0.0.0/8, ::1)
    - Private networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7)
    - Link-local (169.254.0.0/16, fe80::/10)
    - Multicast (224.0.0.0/4, ff00::/8)
    - Unspecified / zero (0.0.0.0/8, ::)
    - CGNAT (100.64.0.0/10)
    - Reserved & documentation networks (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24, 2001:db8::/32)
    - IPv4-mapped IPv6 addresses (::ffff:x.x.x.x) with unsafe IPv4 targets
    - 6to4 addresses (2002::/16) with unsafe IPv4 targets
    """
    try:
        if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            address = value
        else:
            address = ipaddress.ip_address(str(value).strip())
    except (ValueError, TypeError):
        return False

    # Check for IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            return is_safe_ip(address.ipv4_mapped)
        if address.sixtofour:
            return is_safe_ip(address.sixtofour)
        if getattr(address, "is_site_local", False):
            return False

    if any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    ):
        return False

    for network in EXTRA_BLOCKED_NETWORKS:
        if address in network:
            return False

    return True


def resolve_safe_ips(hostname: str, port: Optional[int] = None) -> List[str]:
    """Resolve a hostname and return a list of validated safe IP address strings.

    If any resolved IP is unsafe, or if resolution fails, returns an empty list.
    """
    if not hostname:
        return []

    # If hostname is already an IP literal
    try:
        ip = ipaddress.ip_address(hostname)
        if is_safe_ip(ip):
            return [str(ip)]
        return []
    except ValueError:
        pass

    try:
        addresses = socket.getaddrinfo(
            hostname,
            port or 80,
            type=socket.SOCK_STREAM,
        )
        if not addresses:
            return []

        resolved_ips = []
        for address in addresses:
            ip_str = address[4][0]
            if not is_safe_ip(ip_str):
                return []
            if ip_str not in resolved_ips:
                resolved_ips.append(ip_str)

        return resolved_ips
    except (OSError, ValueError, TypeError):
        return []


def validate_url(url: str) -> bool:
    """Validate a URL before making a server-side request.

    Hostnames are resolved here and every returned IPv4/IPv6 address must be
    publicly routable. Redirects must also be validated per hop.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ALLOWED_SCHEMES or not parsed.hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False

        # Validate port if specified
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            return False

        hostname = parsed.hostname
        safe_ips = resolve_safe_ips(hostname, parsed.port)
        return len(safe_ips) > 0
    except (OSError, ValueError, TypeError):
        return False
