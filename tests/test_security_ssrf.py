"""Security regression test suite for SSRF and DNS rebinding protections (PY-01, PY-05)."""

from unittest.mock import patch, MagicMock
import socket
import pytest
import httpcore
import httpx

from src.utils.safe_url import is_safe_ip, validate_url, resolve_safe_ips
from src.utils.safe_http import SafeSyncBackend, create_safe_client, safe_request


# =========================================================================
# IP Address Safety Checks (PY-01)
# =========================================================================

def test_is_safe_ip_loopback():
    assert not is_safe_ip("127.0.0.1")
    assert not is_safe_ip("127.0.0.2")
    assert not is_safe_ip("127.255.255.255")
    assert not is_safe_ip("::1")


def test_is_safe_ip_private_ranges():
    assert not is_safe_ip("10.0.0.1")
    assert not is_safe_ip("10.255.255.254")
    assert not is_safe_ip("172.16.0.1")
    assert not is_safe_ip("172.31.255.254")
    assert not is_safe_ip("192.168.0.1")
    assert not is_safe_ip("192.168.1.100")
    assert not is_safe_ip("fc00::1")
    assert not is_safe_ip("fd00::1")


def test_is_safe_ip_link_local_and_cloud_metadata():
    assert not is_safe_ip("169.254.169.254")  # AWS/GCP metadata
    assert not is_safe_ip("169.254.1.1")
    assert not is_safe_ip("fe80::1")


def test_is_safe_ip_multicast_and_unspecified():
    assert not is_safe_ip("0.0.0.0")
    assert not is_safe_ip("::")
    assert not is_safe_ip("224.0.0.1")
    assert not is_safe_ip("ff02::1")


def test_is_safe_ip_cgnat_and_documentation():
    assert not is_safe_ip("100.64.0.1")       # CGNAT
    assert not is_safe_ip("100.127.255.254")  # CGNAT
    assert not is_safe_ip("192.0.2.1")        # TEST-NET-1
    assert not is_safe_ip("198.51.100.1")     # TEST-NET-2
    assert not is_safe_ip("203.0.113.1")      # TEST-NET-3
    assert not is_safe_ip("2001:db8::1")      # Doc IPv6


def test_is_safe_ip_ipv4_mapped_ipv6():
    assert not is_safe_ip("::ffff:127.0.0.1")
    assert not is_safe_ip("::ffff:10.0.0.1")
    assert not is_safe_ip("::ffff:169.254.169.254")
    assert not is_safe_ip("::ffff:192.168.1.1")
    # Public IPv4 mapped should be safe
    assert is_safe_ip("::ffff:93.184.216.34")


def test_is_safe_ip_public_addresses():
    assert is_safe_ip("93.184.216.34")
    assert is_safe_ip("8.8.8.8")
    assert is_safe_ip("1.1.1.1")
    assert is_safe_ip("2606:4700:4700::1111")


def test_is_safe_ip_invalid_formats():
    assert not is_safe_ip("")
    assert not is_safe_ip("not-an-ip")
    assert not is_safe_ip("999.999.999.999")
    assert not is_safe_ip(None)


# =========================================================================
# URL Validation Checks (PY-01, PY-05)
# =========================================================================

def test_validate_url_disallowed_schemes():
    assert not validate_url("file:///etc/passwd")
    assert not validate_url("ftp://example.com/file.txt")
    assert not validate_url("gopher://example.com/")
    assert not validate_url("javascript:alert(1)")
    assert not validate_url("data:text/html,test")


def test_validate_url_userinfo_rejected():
    assert not validate_url("https://user:password@example.com/image.jpg")
    assert not validate_url("http://admin:@example.com/")


def test_validate_url_invalid_ports():
    assert not validate_url("https://example.com:0/test")
    assert not validate_url("https://example.com:70000/test")


def test_validate_url_dns_resolution_private_ip():
    records = [(None, None, None, None, ("127.0.0.1", 0))]
    with patch("src.utils.safe_url.socket.getaddrinfo", return_value=records):
        assert not validate_url("https://attacker.example/image.jpg")


def test_validate_url_mixed_dns_records_rejected():
    # If a hostname returns both public and private IPs, reject it
    records = [
        (None, None, None, None, ("93.184.216.34", 0)),
        (None, None, None, None, ("10.0.0.1", 0)),
    ]
    with patch("src.utils.safe_url.socket.getaddrinfo", return_value=records):
        assert not validate_url("https://mixed-attacker.example/image.jpg")


def test_validate_url_public_domain_passes():
    records = [(None, None, None, None, ("93.184.216.34", 0))]
    with patch("src.utils.safe_url.socket.getaddrinfo", return_value=records):
        assert validate_url("https://example.com/image.jpg")


# =========================================================================
# SafeSyncBackend & DNS Rebinding Resistance (PY-01)
# =========================================================================

def test_safe_sync_backend_blocks_private_ip_at_socket_layer():
    backend = SafeSyncBackend()
    records = [(None, None, None, None, ("127.0.0.1", 80))]
    with patch("socket.getaddrinfo", return_value=records):
        with pytest.raises(httpcore.ConnectError, match="blocked"):
            backend.connect_tcp("rebound.example.com", 80)


def test_safe_sync_backend_blocks_unix_socket():
    backend = SafeSyncBackend()
    with pytest.raises(httpcore.ConnectError, match="disallowed"):
        backend.connect_unix_socket("/var/run/docker.sock")


def test_safe_sync_backend_connects_to_validated_ip():
    backend = SafeSyncBackend()
    records = [(None, None, None, None, ("93.184.216.34", 80))]
    mock_sock = MagicMock()
    with patch("socket.getaddrinfo", return_value=records):
        with patch("socket.create_connection", return_value=mock_sock) as mock_create:
            stream = backend.connect_tcp("example.com", 80)
            mock_create.assert_called_once_with(
                ("93.184.216.34", 80),
                None,
                source_address=None,
            )
            assert stream is not None


# =========================================================================
# Redirect SSRF Protection (PY-01, PY-05)
# =========================================================================

def test_safe_request_blocks_redirect_to_private_ip():
    client = create_safe_client()
    url = "https://example.com/initial"
    redirect_target = "http://127.0.0.1/admin"

    response_302 = httpx.Response(
        302,
        headers={"Location": redirect_target},
        request=httpx.Request("GET", url),
    )

    with patch.object(client, "request", return_value=response_302):
        with patch("src.utils.safe_http.validate_url") as mock_val:
            # Initial passes, target fails
            mock_val.side_effect = lambda u: u == url
            with pytest.raises(httpx.InvalidURL, match="Unsafe redirect target"):
                safe_request(client, "GET", url)
