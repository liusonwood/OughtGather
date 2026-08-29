"""Centralized safe HTTP networking layer for OughtGather.

Provides DNS-rebinding-safe HTTP transport, redirect validation per-hop,
timeouts, and response size guards for all outbound network requests.
"""

import socket
import typing
from urllib.parse import urljoin, urlparse

import httpcore
import httpcore._backends.sync
import httpx

from src.utils.logger import get_logger
from src.utils.safe_url import is_safe_ip, validate_url

logger = get_logger()

DEFAULT_MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = 10.0
MAX_FEED_BYTES = 10 * 1024 * 1024      # 10 MB
MAX_ARTICLE_BYTES = 5 * 1024 * 1024    # 5 MB
MAX_IMAGE_DOWNLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


class SafeSyncBackend(httpcore._backends.sync.SyncBackend):
    """httpcore network backend that enforces SSRF checks at the TCP socket layer.

    Resolves the hostname, validates all resolved IP addresses, and connects
    directly to the validated IP to prevent DNS rebinding TOCTOU attacks.
    """

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: typing.Optional[float] = None,
        local_address: typing.Optional[str] = None,
        socket_options: typing.Optional[typing.Iterable[httpcore._backends.sync.SOCKET_OPTION]] = None,
    ) -> httpcore._backends.sync.NetworkStream:
        if socket_options is None:
            socket_options = []

        # Resolve and validate host at the socket creation level
        try:
            addresses = socket.getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        except Exception as exc:
            raise httpcore.ConnectError(f"DNS resolution failed for {host}: {exc}") from exc

        if not addresses:
            raise httpcore.ConnectError(f"No DNS records found for {host}")

        # Ensure every resolved IP is publicly routable and safe
        for addr in addresses:
            ip_str = addr[4][0]
            if not is_safe_ip(ip_str):
                raise httpcore.ConnectError(
                    f"Connection to unsafe/private destination blocked: {host} -> {ip_str}"
                )

        # Select the first validated safe IP to connect to directly
        target_ip = addresses[0][4][0]
        address = (target_ip, port)
        source_address = None if local_address is None else (local_address, 0)
        exc_map: httpcore._backends.sync.ExceptionMapping = {
            socket.timeout: httpcore.ConnectTimeout,
            OSError: httpcore.ConnectError,
        }

        with httpcore._backends.sync.map_exceptions(exc_map):
            sock = socket.create_connection(
                address,
                timeout,
                source_address=source_address,
            )
            for option in socket_options:
                sock.setsockopt(*option)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        return httpcore._backends.sync.SyncStream(sock)

    def connect_unix_socket(
        self,
        path: str,
        timeout: typing.Optional[float] = None,
        socket_options: typing.Optional[typing.Iterable[httpcore._backends.sync.SOCKET_OPTION]] = None,
    ) -> httpcore._backends.sync.NetworkStream:
        raise httpcore.ConnectError("Unix socket connections are disallowed")


class SafeTransport(httpx.HTTPTransport):
    """httpx HTTPTransport configured with SafeSyncBackend."""

    def __init__(
        self,
        verify: typing.Union[typing.Any, str, bool] = True,
        cert: typing.Optional[typing.Any] = None,
        trust_env: bool = True,
        http1: bool = True,
        http2: bool = False,
        limits: typing.Optional[httpx.Limits] = None,
        **kwargs,
    ):
        limits = limits or httpx.Limits(max_connections=100, max_keepalive_connections=20)
        super().__init__(
            verify=verify,
            cert=cert,
            trust_env=trust_env,
            http1=http1,
            http2=http2,
            limits=limits,
            **kwargs,
        )
        from httpx._config import create_ssl_context
        ssl_context = create_ssl_context(verify=verify, cert=cert, trust_env=trust_env)
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl_context,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=http1,
            http2=http2,
            network_backend=SafeSyncBackend(),
        )


def create_safe_client(
    timeout: float = DEFAULT_TIMEOUT,
    limits: typing.Optional[httpx.Limits] = None,
    **kwargs,
) -> httpx.Client:
    """Create an httpx.Client with DNS-rebinding-safe transport and default limits."""
    if limits is None:
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)

    # Disable automatic redirect following in httpx so every redirect hop is validated
    kwargs.setdefault("follow_redirects", False)

    return httpx.Client(
        transport=SafeTransport(),
        timeout=timeout,
        limits=limits,
        **kwargs,
    )


def safe_request(
    client: httpx.Client,
    method: str,
    url: str,
    headers: typing.Optional[typing.Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    json: typing.Optional[typing.Any] = None,
    data: typing.Optional[typing.Any] = None,
    params: typing.Optional[typing.Dict[str, typing.Any]] = None,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_response_bytes: typing.Optional[int] = None,
    raise_for_status: bool = True,
) -> httpx.Response:
    """Send an HTTP request with per-hop URL validation and response size limits.

    Validates initial URL and all subsequent redirect targets before connecting.
    """
    if not validate_url(url):
        raise httpx.InvalidURL(f"Unsafe URL target: {url}")

    req_headers = dict(headers or {})
    current_url = url
    redirect_count = 0

    response = client.request(
        method,
        current_url,
        headers=req_headers,
        timeout=timeout,
        json=json,
        data=data,
        params=params,
        follow_redirects=False,
    )

    # Stream/read with size limit
    _read_response_with_limit(response, max_response_bytes)

    while True:
        status_code = getattr(response, "status_code", None)
        is_redirect = isinstance(status_code, int) and 300 <= status_code < 400
        location = response.headers.get("location") if is_redirect else None
        if not location:
            break

        if redirect_count >= max_redirects:
            raise httpx.TooManyRedirects(
                f"Exceeded maximum of {max_redirects} redirects",
                request=response.request,
            )

        current_url = urljoin(str(response.request.url), location)
        if not validate_url(current_url):
            raise httpx.InvalidURL(f"Unsafe redirect target: {current_url}")

        next_headers = dict(response.request.headers)
        next_headers.pop("host", None)
        next_headers.pop("content-length", None)

        response = client.request(
            response.request.method,
            current_url,
            headers=next_headers,
            content=response.request.content,
            timeout=timeout,
            follow_redirects=False,
        )
        _read_response_with_limit(response, max_response_bytes)
        redirect_count += 1

    if raise_for_status:
        if isinstance(response.status_code, int) and response.status_code != 200:
            raise httpx.HTTPStatusError(
                f"Unexpected HTTP status {response.status_code}",
                request=response.request,
                response=response,
            )
        response.raise_for_status()

    return response


def _read_response_with_limit(
    response: httpx.Response,
    max_bytes: typing.Optional[int] = None,
) -> None:
    """Read response content enforcing maximum byte size limit."""
    if max_bytes is None:
        response.read()
        return

    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise ValueError(
                    f"Response Content-Length ({content_length}) exceeds maximum limit ({max_bytes} bytes)"
                )
        except ValueError as e:
            if "exceeds maximum limit" in str(e):
                raise

    if hasattr(response, "_content") and response._content is not None:
        if len(response._content) > max_bytes:
            raise ValueError(
                f"Response body exceeded maximum limit ({max_bytes} bytes)"
            )
        return

    # Read up to max_bytes + 1
    content_chunks = []
    total_bytes = 0
    for chunk in response.iter_bytes():
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise ValueError(
                f"Response body exceeded maximum limit ({max_bytes} bytes)"
            )
        content_chunks.append(chunk)

    response._content = b"".join(content_chunks)
