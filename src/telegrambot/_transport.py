"""One shared bounded HTTPS fetch reused by every source adapter.

Each adapter keeps its own error class, exact allowed hosts, limits,
headers, and user-facing diagnostics; only the identical urllib
mechanics live here. Every failure is a BoundedFetchError with a stable
diagnostic code that adapters translate without exposing response text.
"""

import http.client
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, FrozenSet, Optional, Tuple


class BoundedFetchError(Exception):
    """Transport failure carrying a stable code and no user-facing text."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: Optional[int] = None,
        payload: Optional[bytes] = None,
        retry_after: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.payload = payload
        self.retry_after = retry_after


class _BoundedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(
        self,
        is_allowed_url: Optional[Callable[[str], bool]],
    ) -> None:
        super().__init__()
        self.is_allowed_url = is_allowed_url

    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        if self.is_allowed_url is None or not self.is_allowed_url(new_url):
            raise BoundedFetchError(
                "Redirected outside the allowed host",
                code="REDIRECT",
            )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def _classify_timeout(exc: BaseException) -> bool:
    return isinstance(exc, (TimeoutError, socket.timeout)) or (
        isinstance(exc, urllib.error.URLError)
        and isinstance(exc.reason, (TimeoutError, socket.timeout))
    )


def _bounded_error_body(
    exc: urllib.error.HTTPError,
    limit_bytes: int,
    read_error_body: bool,
) -> Optional[bytes]:
    if not read_error_body:
        return None
    try:
        payload = exc.read(limit_bytes + 1)
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as read_error:
        raise BoundedFetchError(
            "HTTP error response could not be read",
            code="NETWORK",
        ) from read_error
    if len(payload) > limit_bytes:
        raise BoundedFetchError(
            "HTTP error response was too large",
            code="TOO-LARGE",
        ) from None
    return payload


def fetch_bounded(
    url: str,
    *,
    is_allowed_url: Callable[[str], bool],
    limit_bytes: int,
    timeout_seconds: float,
    headers: Dict[str, str],
    accepted_types: Optional[FrozenSet[str]] = None,
    method: str = "GET",
    data: Optional[bytes] = None,
    follow_redirects: bool = True,
    read_error_body: bool = False,
) -> Tuple[bytes, str, str]:
    """Fetch one bounded response from an explicitly allowed HTTPS URL.

    Returns (payload, final_url, content_type). Raises BoundedFetchError
    with code URL-POLICY, REDIRECT, CONTENT-TYPE, HTTP-<n>, TIMEOUT,
    NETWORK, or TOO-LARGE. HTTP errors carry the raw Retry-After header,
    plus the bounded error body when read_error_body is set.
    """

    if not is_allowed_url(url):
        raise BoundedFetchError(
            "URL is outside the allowed host",
            code="URL-POLICY",
        )
    request = urllib.request.Request(
        url,
        data=data,
        headers=dict(headers),
        method=method,
    )
    opener = urllib.request.build_opener(
        _BoundedRedirectHandler(is_allowed_url if follow_redirects else None)
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            if not is_allowed_url(final_url):
                raise BoundedFetchError(
                    "Response URL is outside the allowed host",
                    code="REDIRECT",
                )
            content_type = response.headers.get_content_type()
            if (
                accepted_types is not None
                and content_type not in accepted_types
            ):
                raise BoundedFetchError(
                    "Unexpected content type",
                    code="CONTENT-TYPE",
                )
            payload = response.read(limit_bytes + 1)
    except BoundedFetchError:
        raise
    except urllib.error.HTTPError as exc:
        raise BoundedFetchError(
            f"HTTP status {exc.code}",
            code=f"HTTP-{exc.code}",
            status=exc.code,
            payload=_bounded_error_body(exc, limit_bytes, read_error_body),
            retry_after=(
                exc.headers.get("Retry-After")
                if exc.headers is not None
                else None
            ),
        ) from exc
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as exc:
        timed_out = _classify_timeout(exc)
        raise BoundedFetchError(
            "Request timed out" if timed_out else "Network request failed",
            code="TIMEOUT" if timed_out else "NETWORK",
        ) from exc
    if len(payload) > limit_bytes:
        raise BoundedFetchError(
            "Response exceeded the configured size limit",
            code="TOO-LARGE",
        )
    return payload, final_url, content_type
