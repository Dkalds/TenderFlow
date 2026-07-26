"""Validación estricta de URLs salientes para prevenir SSRF y DNS rebinding."""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass

DNS_REBINDING_SUFFIXES = (
    ".nip.io",
    ".xip.io",
    ".sslip.io",
    ".localtest.me",
    ".lvh.me",
    ".traefik.me",
)


@dataclass(frozen=True)
class PinnedHttpsTarget:
    """A validated HTTPS destination with one DNS answer selected for dialing."""

    hostname: str
    address: str
    port: int
    request_uri: str


def _is_public_address(raw: str) -> bool:
    """Acepta exclusivamente direcciones globales, normalizando IPv4-mapped IPv6."""
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global


def validate_outbound_url(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
    allowed_schemes: frozenset[str] = frozenset({"https"}),
) -> str:
    """Valida una URL sin reemplazar el host y por tanto sin romper TLS/SNI.

    El consumidor debe prohibir redirecciones o validar de nuevo cada salto.
    Una sola respuesta DNS no global invalida por completo el destino.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in allowed_schemes:
        raise ValueError("Esquema URL no permitido")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("URL con credenciales o fragmento no permitida")
    host = parsed.hostname
    if not host:
        raise ValueError("URL sin hostname")
    if parsed.port not in (None, 443):
        raise ValueError("Puerto URL no permitido")
    host_l = host.lower()
    if any(host_l.endswith(suffix) for suffix in DNS_REBINDING_SUFFIXES):
        raise ValueError("Dominio de DNS rebinding bloqueado")

    rules = tuple(rule.strip().lower() for rule in (allowed_hosts or ()) if rule.strip())
    if rules and not any(
        host_l == rule.lstrip("*.") or (rule.startswith("*.") and host_l.endswith(rule[1:]))
        for rule in rules
    ):
        raise ValueError("Host no incluido en la allowlist")

    try:
        addrs = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {host}") from exc
    if not addrs or any(not _is_public_address(str(info[4][0])) for info in addrs):
        raise ValueError("Host resuelve a una dirección no global")
    return url


def resolve_pinned_https_target(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
) -> PinnedHttpsTarget:
    """Resolve a public HTTPS destination once for a pinned TLS connection.

    The returned address is validated immediately before it is used. Callers
    must dial that address while retaining ``hostname`` for HTTP Host, TLS SNI
    and certificate verification; that prevents a later DNS lookup from
    redirecting the connection to an internal address.
    """
    validate_outbound_url(url, allowed_hosts=allowed_hosts)
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname
    if hostname is None:  # Defensive: validate_outbound_url already checks this.
        raise ValueError("URL sin hostname")
    try:
        answers = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {hostname}") from exc
    addresses = tuple(dict.fromkeys(str(answer[4][0]) for answer in answers))
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise ValueError("Host resuelve a una direcciÃ³n no global")
    request_uri = parsed.path or "/"
    if parsed.params:
        request_uri += f";{parsed.params}"
    if parsed.query:
        request_uri += f"?{parsed.query}"
    return PinnedHttpsTarget(
        hostname=hostname,
        address=addresses[0],
        port=parsed.port or 443,
        request_uri=request_uri,
    )


def is_ssrf_url(url: str) -> bool:
    """True cuando una URL HTTP(S) no puede usarse de forma segura."""
    try:
        validate_outbound_url(url, allowed_schemes=frozenset({"http", "https"}))
        return False
    except ValueError:
        return True


def resolve_and_validate(url: str) -> str:
    """Compatibilidad para callers legacy que necesitan fijar una IP.

    Solo debe usarse para HTTP no-TLS. Para HTTPS, usar
    :func:`validate_outbound_url` con una allowlist, ya que reemplazar el host
    por una IP rompe la validación SNI/certificado.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "http":
        raise ValueError("DNS pinning por IP solo permitido para HTTP interno controlado")
    validate_outbound_url(url, allowed_schemes=frozenset({"http"}))
    host = parsed.hostname or ""
    addrs = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    resolved_ip = str(addrs[0][4][0])
    port = parsed.port
    netloc = f"[{resolved_ip}]" if ":" in resolved_ip else resolved_ip
    if port:
        netloc = f"{netloc}:{port}"
    return urllib.parse.urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, "")
    )
