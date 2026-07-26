"""Tests for DNS-pinned outbound HTTPS transport."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared.outbound_http import pinned_https_request
from shared.ssrf import PinnedHttpsTarget


@patch("shared.outbound_http.urllib3.HTTPSConnectionPool")
@patch("shared.outbound_http.resolve_pinned_https_target")
def test_pinned_transport_dials_resolved_ip_but_keeps_tls_hostname(
    mock_resolve: MagicMock, mock_pool_cls: MagicMock
) -> None:
    mock_resolve.return_value = PinnedHttpsTarget(
        hostname="hooks.example.com",
        address="93.184.216.34",
        port=443,
        request_uri="/delivery?event=ping",
    )
    raw_response = MagicMock(status=204, headers={})
    pool = mock_pool_cls.return_value
    pool.urlopen.return_value = raw_response

    response = pinned_https_request(
        "POST",
        "https://hooks.example.com/delivery?event=ping",
        headers={"X-Test": "yes"},
        body=b"{}",
        timeout_seconds=5.0,
        allowed_hosts=frozenset({"hooks.example.com"}),
    )

    assert response.status_code == 204
    mock_pool_cls.assert_called_once_with(
        "93.184.216.34",
        443,
        cert_reqs="CERT_REQUIRED",
        assert_hostname="hooks.example.com",
        server_hostname="hooks.example.com",
        retries=False,
        timeout=mock_pool_cls.call_args.kwargs["timeout"],
    )
    call = pool.urlopen.call_args
    assert call.args == ("POST", "/delivery?event=ping")
    assert call.kwargs["headers"]["Host"] == "hooks.example.com"
    assert call.kwargs["redirect"] is False
    response.close()
    raw_response.release_conn.assert_called_once()
    pool.close.assert_called_once()
