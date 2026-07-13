"""Validación SSRF/DNS-rebinding compartida para entregas HTTP salientes.

Extraído de ``api/routes/webhooks.py`` (RFC llm-dependencia-gestionada §C3.0):
antes solo el ping manual (``POST /webhooks/{id}/ping``) resolvía DNS al
momento de la entrega y pinneaba la IP; ``db/webhooks.py::trigger_event``
(el camino real de notificaciones) confiaba en la validación de *creación*
del webhook, dejando una ventana TOCTOU — un dominio válido al crear el
webhook puede re-resolver a una IP privada por DNS rebinding en el momento
del envío real.

Un solo punto de verdad para ambos llamadores.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse

# Rangos de red privada / reservada para bloquear SSRF
PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

# Dominios usados en DNS rebinding — resuelven a IPs arbitrarias controladas por el atacante
DNS_REBINDING_SUFFIXES = (
    ".nip.io",
    ".xip.io",
    ".sslip.io",
    ".localtest.me",
    ".lvh.me",
    ".traefik.me",
)


def is_ssrf_url(url: str) -> bool:
    """Devuelve True si la URL apunta a una red privada/reservada o dominio de rebinding (SSRF risk)."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        if not host:
            return True

        # Bloquear dominios de DNS rebinding por sufijo (antes de resolver DNS)
        host_lower = host.lower()
        if any(host_lower.endswith(suffix) for suffix in DNS_REBINDING_SUFFIXES):
            return True

        # Resolver DNS y verificar la IP final
        try:
            addrs = socket.getaddrinfo(host, None)
        except socket.gaierror:
            # No resuelve — bloquear por defecto
            return True
        for info in addrs:
            try:
                addr = ipaddress.ip_address(info[4][0])
                for net in PRIVATE_NETWORKS:
                    if addr in net:
                        return True
            except ValueError:
                pass
        return False
    except Exception:
        return True  # cualquier error → bloquear


def resolve_and_validate(url: str) -> str:
    """Resolve DNS at delivery time and return the IP-pinned URL.

    Prevents DNS rebinding (TOCTOU): resolves the hostname NOW,
    validates against private networks, and returns a URL with the
    IP address substituted so ``requests.post`` doesn't re-resolve.

    Raises:
        ValueError: if the URL resolves to a private/reserved IP.
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL sin hostname")

    # Re-check rebinding suffixes at delivery time
    host_lower = host.lower()
    if any(host_lower.endswith(suffix) for suffix in DNS_REBINDING_SUFFIXES):
        raise ValueError(f"Dominio de DNS rebinding bloqueado: {host}")

    try:
        addrs = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {host}: {exc}") from exc

    if not addrs:
        raise ValueError(f"No DNS records for {host}")

    # Pick first resolved IP and validate
    resolved_ip = str(addrs[0][4][0])
    try:
        addr = ipaddress.ip_address(resolved_ip)
    except ValueError as exc:
        raise ValueError(f"Invalid resolved IP {resolved_ip}") from exc

    for net in PRIVATE_NETWORKS:
        if addr in net:
            raise ValueError(f"Resolved IP {resolved_ip} is in private network {net}")

    # Build IP-pinned URL: replace hostname with resolved IP, pass original
    # Host header via requests so TLS SNI and virtual hosts still work.
    port = parsed.port
    if ":" in resolved_ip:  # IPv6
        netloc = f"[{resolved_ip}]:{port}" if port else f"[{resolved_ip}]"
    else:
        netloc = f"{resolved_ip}:{port}" if port else resolved_ip

    pinned_url = urllib.parse.urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )
    return pinned_url
