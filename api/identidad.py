"""Ids de licitación anteriores a una re-key: la resolución que comparten todas las rutas.

RFC ``docs/rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md``. La fase B
(``v164_identidad_placsp_rekey``) re-escribe el ``id_externo`` de las filas de
PLACSP (``2026/LIC/0049`` → ``placsp:<órgano>:2026/LIC/0049``) y deja un alias
por fila en ``licitaciones_id_anterior``. Un cliente que guardó el id viejo
—en una URL, en el cuerpo de una petición, en su integración— sigue llegando a
su expediente hasta el *sunset*:

- :func:`resolver_id_externo` / :func:`resolver_licitacion_id` son
  dependencias de FastAPI para las rutas con el id en la ruta
  (``/licitaciones/{id_externo:path}/…``, ``/licitaciones/{licitacion_id:path}/…``,
  ``/watchlist/items/{id_externo:path}``…), según cómo se llame el parámetro.
- :func:`id_vigente` es lo mismo para un id que llega en el **cuerpo**
  (``pursuits``, ``follows``, cartera, feedback del asistente…): la ruta lo
  llama con su ``Response``.

Cuando resuelve por alias, la respuesta lleva ``Deprecation: true``, ``Sunset``
y ``Link`` hacia el id vigente (``api.errors.deprecate_route``). Un id que no
existe ni tiene alias se devuelve tal cual: cada ruta conserva su 404 o su
validación. Pasado el *sunset* (2027-04-30) se retira la resolución en la API;
la ficha pública sigue redirigiendo (308).

Vive fuera de ``api/routes/licitaciones/`` porque la usan rutas de varias
familias.
"""

from __future__ import annotations

from datetime import date

from fastapi import Response

from api.concurrency import run_db
from api.errors import deprecate_route, sunset_anunciado
from db.repositories.identidad import resolver_id_licitacion
from observability.logging import get_logger

__all__ = [
    "RFC_IDENTIDAD_PLACSP",
    "SUNSET_IDS_ANTERIORES",
    "id_vigente",
    "resolver_id_externo",
    "resolver_licitacion_id",
]

log = get_logger(__name__)

#: Hasta cuándo la API resuelve un `id_externo` anterior a una re-key
#: (`licitaciones_id_anterior`, v163) en vez de responder 404. Lo fija el RFC
#: de identidad PLACSP: seis meses desde la fase B prevista; la ficha pública
#: sigue redirigiendo (308) después. Anunciado con la fase A, el 2026-10-25.
SUNSET_IDS_ANTERIORES = sunset_anunciado(date(2027, 4, 30), anunciado=date(2026, 10, 25))
RFC_IDENTIDAD_PLACSP = "docs/rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md"


async def id_vigente(id_licitacion: str, response: Response | None) -> str:
    """El id vigente de ``id_licitacion``; si llegó por alias, marca ``response``.

    Para ids que llegan en el cuerpo de la petición. Las rutas con el id en la
    ruta usan las dependencias de abajo, que llaman aquí. ``response`` es
    ``None`` en las rutas que devuelven su propia ``Response`` (un stream SSE):
    FastAPI no copia a ella las cabeceras del parámetro, así que ahí el id se
    resuelve sin aviso.
    """
    resuelto = await run_db(resolver_id_licitacion, id_licitacion)
    if resuelto is None or not resuelto.via_alias:
        return id_licitacion
    if response is not None:
        deprecate_route(
            response,
            sunset=SUNSET_IDS_ANTERIORES,
            successor=f"/api/v1/licitaciones/{resuelto.id_externo}",
            rfc=RFC_IDENTIDAD_PLACSP,
        )
    log.info("licitacion_id_anterior_resuelto", pedido=id_licitacion, vigente=resuelto.id_externo)
    return resuelto.id_externo


async def resolver_id_externo(id_externo: str, response: Response) -> str:
    """Dependencia de las rutas con ``{id_externo:path}``: el id vigente.

    Se declara **después** de la dependencia de autenticación: las
    dependencias se resuelven en el orden de los parámetros y un 401 no debe
    necesitar la base de datos.
    """
    return await id_vigente(id_externo, response)


async def resolver_licitacion_id(licitacion_id: str, response: Response) -> str:
    """Lo mismo que :func:`resolver_id_externo`, para rutas con ``{licitacion_id:path}``."""
    return await id_vigente(licitacion_id, response)
