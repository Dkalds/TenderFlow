"""Diagnóstico temporal: qué cabeceras de reenvío llegan a la API en producción.

**Temporal.** Existe para decidir de dónde sale la IP del cliente
([RFC 2026-10-24](../docs/rfc/2026-10-24-rfc-ip-del-cliente-tras-vercel-y-render.md)).
Se retira en el mismo cambio que aplique la opción elegida.

El 2026-10-24 el log de Render mostró que el ``client_ip`` de ``http_request``
es siempre un salto interno ``10.19x.x.x`` del proxy de Render, distinto por
conexión, así que las cuotas por IP no distinguen usuarios. Para elegir el
arreglo hace falta saber qué cadena de ``X-Forwarded-For`` llega, qué
cabeceras de IP añaden Vercel, Cloudflare y Render, y cuál coincide con la del
visitante. Nada de eso se lee desde el repo: lo dice esta línea de log.

Qué registra (``proxy_cabeceras_diag``), solo en ``/api/v1/auth/*`` —donde
viven las cuotas que importan y ``GET /auth/me``, que basta con abrir la app
para provocar—:

* los **nombres** de todas las cabeceras de la petición, sin valores;
* el peer TCP tal como lo deja uvicorn y si uvicorn lo reescribió (puerto 0);
* cada salto de ``X-Forwarded-For`` y cada cabecera de IP conocida, **nunca la
  IP entera**: su clase (privada, pública…), su red truncada (``/16`` en IPv4,
  ``/32`` en IPv6) y una huella de 8 caracteres;
* la IP que eligió ``_trusted_client_ip``, con el mismo formato.

La huella es un HMAC con una clave aleatoria **por proceso** que no se guarda
en ningún sitio: dentro de un mismo proceso la misma IP da la misma huella
(así se ve que ``x-real-ip`` es el primer salto, o que dos usuarios difieren),
y tras un reinicio no hay forma de volver a calcularla ni de enlazarla con
nada. Es menos de lo que ya registra hoy ``http_request``, que lleva
``client_ip`` en claro.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
from typing import Final

from starlette.requests import HTTPConnection

from observability.logging import get_logger

log = get_logger(__name__)

#: Prefijo de las rutas en las que se emite la línea.
PREFIJO_DIAGNOSTICO: Final = "/api/v1/auth/"

#: Cabeceras cuyo valor es una IP (o una lista de ellas) y se describen.
CABECERAS_IP: Final = (
    "x-real-ip",
    "true-client-ip",
    "cf-connecting-ip",
    "x-vercel-forwarded-for",
    "x-client-ip",
    "fastly-client-ip",
)

#: Cabeceras sin dato personal cuyo valor sí ayuda a saber por dónde vino la
#: petición: el host que pidió el visitante y el esquema.
CABECERAS_VALOR_LITERAL: Final = ("x-forwarded-host", "x-forwarded-proto")

#: Tope de saltos y de nombres de cabecera por línea: una cabecera inflada por
#: el cliente no debe convertir el log en un vector de volumen.
MAX_SALTOS: Final = 8
MAX_NOMBRES: Final = 60
MAX_LITERAL: Final = 100

_CLAVE_PROCESO: Final = secrets.token_bytes(16)


def _huella(valor: str) -> str:
    """HMAC truncado con la clave del proceso: comparable dentro de él, nada más."""
    return hmac.new(_CLAVE_PROCESO, valor.encode(), hashlib.sha256).hexdigest()[:8]


def _clase(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if ip.is_loopback:
        return "loopback"
    if ip.is_private:
        return "privada"
    if ip.is_global:
        return "publica"
    return "reservada"


def _red(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Red truncada: ``/16`` en IPv4 (``a.b.x.x``) y ``/32`` en IPv6."""
    prefijo = 16 if ip.version == 4 else 32
    return str(ipaddress.ip_network(f"{ip}/{prefijo}", strict=False))


def describir_ip(valor: str | None) -> dict[str, str] | None:
    """Clase, red truncada y huella de una IP, sin la IP. ``None`` si no hay valor.

    Acepta ``host:puerto`` y ``[v6]:puerto`` porque algunos proxies los escriben
    así en ``X-Forwarded-For``. Lo que no parsea como IP se describe como
    ``invalida`` con su huella, sin el texto: lo escribe quien manda la petición.
    """
    if valor is None:
        return None
    texto = valor.strip()
    if not texto:
        return {"clase": "vacia"}
    candidato = texto
    if candidato.startswith("[") and "]" in candidato:
        candidato = candidato[1 : candidato.index("]")]
    elif candidato.count(":") == 1:
        candidato = candidato.split(":", 1)[0]
    try:
        ip = ipaddress.ip_address(candidato)
    except ValueError:
        return {"clase": "invalida", "h": _huella(texto)}
    return {"clase": _clase(ip), "red": _red(ip), "h": _huella(str(ip))}


def _saltos(cabecera: str) -> tuple[list[dict[str, str]], int]:
    partes = cabecera.split(",")
    descritos = [d for d in (describir_ip(p) for p in partes[:MAX_SALTOS]) if d is not None]
    return descritos, len(partes)


def _origen_acreditado_seguro(conexion: HTTPConnection) -> bool:
    """Si la petición trae un secreto de origen aceptado; False ante cualquier fallo."""
    # Import diferido: api.middleware importa este módulo.
    from api.middleware import _origen_acreditado, _secretos_de_origen
    from config import settings

    try:
        return _origen_acreditado(conexion, _secretos_de_origen(settings))
    except Exception:
        return False


def describir_peticion(conexion: HTTPConnection, ip_elegida: str) -> dict[str, object]:
    """Campos de la línea ``proxy_cabeceras_diag`` para una petición."""
    cabeceras = conexion.headers
    nombres = sorted({nombre.lower() for nombre in cabeceras})
    peer = conexion.client
    campos: dict[str, object] = {
        "cabeceras": nombres[:MAX_NOMBRES],
        "peer": describir_ip(peer.host if peer else None),
        # uvicorn (--proxy-headers) reescribe el peer con el salto elegido de
        # X-Forwarded-For y le pone el puerto que traiga ese salto, 0 si no
        # trae: un puerto efímero real dice que no lo reescribió.
        "peer_reescrito": bool(peer and peer.port == 0),
        "ip_elegida": describir_ip(ip_elegida),
        # Opción B aplicada: si la cabecera del secreto casó. Solo el booleano;
        # el valor de la cabecera no sale nunca (su nombre sí, en `cabeceras`).
        "origen_acreditado": _origen_acreditado_seguro(conexion),
    }
    xff = cabeceras.get("x-forwarded-for")
    if xff is not None:
        saltos, total = _saltos(xff)
        campos["xff"] = saltos
        campos["xff_saltos"] = total
    for nombre in CABECERAS_IP:
        valor = cabeceras.get(nombre)
        if valor is not None:
            # Puede ser una lista (x-vercel-forwarded-for): basta el primero
            # para compararlo con los saltos de X-Forwarded-For.
            campos[nombre.replace("-", "_")] = describir_ip(valor.split(",")[0])
    for nombre in CABECERAS_VALOR_LITERAL:
        valor = cabeceras.get(nombre)
        if valor is not None:
            campos[nombre.replace("-", "_")] = valor[:MAX_LITERAL]
    return campos


def registrar_cabeceras_proxy(conexion: HTTPConnection, path: str, ip_elegida: str) -> None:
    """Emite ``proxy_cabeceras_diag`` si ``path`` es de ``/api/v1/auth/``. Nunca lanza."""
    if not path.startswith(PREFIJO_DIAGNOSTICO):
        return
    try:
        log.info("proxy_cabeceras_diag", path=path, **describir_peticion(conexion, ip_elegida))
    except Exception:
        # Un diagnóstico no puede tumbar el access log ni la respuesta.
        log.debug("proxy_cabeceras_diag_fallo", exc_info=True)
