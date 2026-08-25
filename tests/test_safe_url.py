from unittest.mock import patch

from src.utils.safe_url import is_safe_ip, validate_url


def test_rejects_disallowed_schemes_and_credentials():
    assert not validate_url("file:///etc/passwd")
    assert not validate_url("ftp://example.com/image.jpg")
    assert not validate_url("https://user:password@example.com/image.jpg")


def test_rejects_non_public_ip_ranges():
    for address in ("127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.1.1", "::1", "fc00::1", "fe80::1"):
        assert not is_safe_ip(address)


def test_rejects_hostname_resolving_to_private_address():
    records = [(None, None, None, None, ("10.0.0.5", 0))]
    with patch("src.utils.safe_url.socket.getaddrinfo", return_value=records):
        assert not validate_url("https://attacker.example/image.jpg")


def test_accepts_hostname_with_only_public_addresses():
    records = [(None, None, None, None, ("93.184.216.34", 0))]
    with patch("src.utils.safe_url.socket.getaddrinfo", return_value=records):
        assert validate_url("https://example.test/image.jpg")
