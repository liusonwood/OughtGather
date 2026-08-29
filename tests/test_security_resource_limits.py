"""Security regression tests for resource limits and protocol allowlists (PY-06, PY-07)."""

from unittest.mock import MagicMock, patch
import pytest
import httpx

from src.config import ContentSource
from src.fetchers.base import BaseFetcher
from src.utils.safe_http import safe_request, create_safe_client


class DummyFetcher(BaseFetcher):
    type_name = "dummy_test"

    def fetch(self):
        return None


# =========================================================================
# Browser Protocol Allowlist (PY-07)
# =========================================================================

def test_browser_route_allows_http_and_https():
    fetcher = DummyFetcher(ContentSource(type="web", src="https://example.com"))
    mock_route = MagicMock()
    mock_route.request.url = "https://example.com/page"

    with patch("src.fetchers.base.validate_url", return_value=True):
        fetcher._handle_browser_route(mock_route)
        mock_route.continue_.assert_called_once()
        mock_route.abort.assert_not_called()


def test_browser_route_blocks_non_http_protocols():
    fetcher = DummyFetcher(ContentSource(type="web", src="https://example.com"))

    for blocked_url in (
        "file:///etc/passwd",
        "ftp://example.com/file",
        "ws://example.com/socket",
        "wss://example.com/socket",
        "chrome://settings",
        "chrome-extension://xyz/manifest.json",
    ):
        mock_route = MagicMock()
        mock_route.request.url = blocked_url

        fetcher._handle_browser_route(mock_route)
        mock_route.abort.assert_called_once()
        mock_route.continue_.assert_not_called()


def test_browser_route_blocks_private_ip():
    fetcher = DummyFetcher(ContentSource(type="web", src="https://example.com"))
    mock_route = MagicMock()
    mock_route.request.url = "http://127.0.0.1:8080/admin"

    with patch("src.fetchers.base.validate_url", return_value=False):
        fetcher._handle_browser_route(mock_route)
        mock_route.abort.assert_called_once()
        mock_route.continue_.assert_not_called()


# =========================================================================
# Resource Limits (PY-06)
# =========================================================================

def test_safe_request_enforces_max_response_bytes():
    client = create_safe_client()
    url = "https://example.com/large.html"

    # 10 bytes limit
    oversized_response = httpx.Response(
        200,
        content=b"x" * 100,
        request=httpx.Request("GET", url),
    )

    with patch.object(client, "request", return_value=oversized_response):
        with patch("src.utils.safe_http.validate_url", return_value=True):
            with pytest.raises(ValueError, match="exceed.*maximum limit"):
                safe_request(client, "GET", url, max_response_bytes=10)


def test_safe_request_enforces_max_redirect_limit():
    client = create_safe_client()
    url = "https://example.com/loop"

    loop_response = httpx.Response(
        302,
        headers={"Location": "https://example.com/loop"},
        request=httpx.Request("GET", url),
    )

    with patch.object(client, "request", return_value=loop_response):
        with patch("src.utils.safe_http.validate_url", return_value=True):
            with pytest.raises(httpx.TooManyRedirects, match="Exceeded maximum of 3 redirects"):
                safe_request(client, "GET", url, max_redirects=3)
