"""Pinned HTTPS transport for security-sensitive outbound requests.

Requests normally resolve a hostname at connect time, after an application has
already validated it. This transport resolves and validates a public address,
then dials that exact address while retaining the original hostname for HTTP
Host, TLS SNI and certificate verification.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import requests
import urllib3

from shared.ssrf import resolve_pinned_https_target


class PinnedHttpsResponse:
    """Small requests-compatible wrapper around a non-preloaded urllib3 response."""

    def __init__(self, pool: urllib3.HTTPSConnectionPool, response: Any) -> None:
        self._pool = pool
        self._response = response
        self.status_code = int(response.status)
        self.headers: Mapping[str, str] = response.headers

    def raise_for_status(self) -> None:
        # Redirects are deliberately rejected. A redirect would need a fresh
        # allowlist + DNS-pinning decision for its new destination.
        if self.status_code >= 300:
            raise requests.HTTPError(f"Pinned HTTPS response status {self.status_code}")

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        yield from self._response.stream(chunk_size, decode_content=True)

    def close(self) -> None:
        self._response.release_conn()
        self._pool.close()

    def __enter__(self) -> PinnedHttpsResponse:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


def pinned_https_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout_seconds: float,
    allowed_hosts: frozenset[str] | None = None,
) -> PinnedHttpsResponse:
    """Perform one HTTPS request without allowing DNS re-resolution or redirects."""
    target = resolve_pinned_https_target(url, allowed_hosts=allowed_hosts)
    request_headers = dict(headers or {})
    host_header = target.hostname if target.port == 443 else f"{target.hostname}:{target.port}"
    request_headers["Host"] = host_header
    pool: urllib3.HTTPSConnectionPool | None = None
    try:
        pool = urllib3.HTTPSConnectionPool(
            target.address,
            target.port,
            cert_reqs="CERT_REQUIRED",
            assert_hostname=target.hostname,
            server_hostname=target.hostname,
            retries=False,
            timeout=urllib3.Timeout(connect=timeout_seconds, read=timeout_seconds),
        )
        response = pool.urlopen(
            method.upper(),
            target.request_uri,
            body=body,
            headers=request_headers,
            redirect=False,
            retries=False,
            preload_content=False,
        )
    except urllib3.exceptions.HTTPError as exc:
        if pool is not None:
            pool.close()
        raise requests.RequestException("Pinned HTTPS request failed") from exc
    return PinnedHttpsResponse(pool, response)
