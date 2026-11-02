"""Repository para audit_log: lecturas para la API y la exportación RGPD.

La escritura y la verificación de la cadena hash viven en ``db/audit.py``
(ADR-022, «Entidades con las dos caras»).
"""

from __future__ import annotations

from typing import Any

from db.database import connect_read, get_table_columns
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

#: Predicado de identidad dual (v129). Parámetros: ``(user_id, user_key, user_id)``.
_IDENT = "(user_id = %s OR (user_key = %s AND (user_id IS NULL OR %s::int IS NULL)))"

#: ``db.audit.log_event`` antepone al detalle estos campos, separados por
#: `` | `` y siempre en cabeza; lo que sigue al último de ellos es el payload
#: libre (JSON o texto) del llamante.
_SEPARADOR = " | "
_CLAVES_ESTRUCTURADAS = frozenset({"event", "outcome", "ip", "resource"})


def descomponer_detalle(detail: str) -> dict[str, str]:
    """Separa el ``detail`` persistido en sus campos de cabecera y el payload.

    Devuelve ``event``/``outcome``/``ip``/``resource`` (los que haya) y, bajo
    ``detail``, el resto de la cadena sin tocar. Un payload que contuviera
    `` | `` no se parte: solo se consumen los prefijos reconocidos y solo
    mientras vengan seguidos desde el principio.
    """
    partes = detail.split(_SEPARADOR)
    campos: dict[str, str] = {}
    indice = len(partes)
    for posicion, parte in enumerate(partes):
        clave, separador, valor = parte.partition("=")
        if not separador or clave not in _CLAVES_ESTRUCTURADAS:
            indice = posicion
            break
        campos[clave] = valor
    campos["detail"] = _SEPARADOR.join(partes[indice:])
    return campos


def patron_recurso_organizacion(organization_id: int) -> str:
    """Regex (POSIX, sirve también en ``re``) de los eventos de una organización.

    Anclada a la **cabecera** que escribe ``db.audit.componer_detalle``
    (``event | outcome | [ip |] resource=...``): el recurso solo cuenta si ocupa
    su sitio en la cabecera. Antes bastaba un `` | resource=org:7 | `` en
    cualquier parte de ``detail`` —el nombre de una API key o de un webhook
    llega ahí— para plantar un evento en el rastro de otra organización. Los
    campos de cabecera no pueden contener ``|`` (el escritor lo quita), así que
    ``[^|]*`` no se desborda hacia el payload. Filas anteriores a la defensa del
    escritor también quedan cubiertas: el filtro no mira su payload.
    """
    return (
        r"^event=[^|]* \| outcome=[^|]* \| (ip=[^|]* \| )?"
        rf"resource=(org|organization):{int(organization_id)}( \||$)"
    )


def _actor_user_id(fila: dict[str, Any]) -> int | None:
    """Actor como ``users.id``: la columna de v129 y, si falta, la clave en texto."""
    if fila.get("user_id") is not None:
        return int(fila["user_id"])
    clave = str(fila.get("user_key") or "")
    clave = clave.removeprefix("user:")
    return int(clave) if clave.isdigit() else None


def _proyectar_entrada(fila: dict[str, Any]) -> dict[str, Any]:
    """Forma que publica ``shared.dto.AuditEntryOut``; el DTO la valida."""
    campos = descomponer_detalle(str(fila.get("detail") or ""))
    return {
        "id": int(fila["id"]),
        "ts": str(fila["created_at"]),
        "event_type": str(fila["action"]),
        "actor_user_id": _actor_user_id(fila),
        "outcome": campos.get("outcome", ""),
        "resource": campos.get("resource"),
        "detail": campos["detail"],
    }


class AuditRepository:
    """Acceso de lectura a la tabla ``audit_log``."""

    def export_by_user_key(self, user_key: str, user_id: int | None = None) -> list[dict[str, Any]]:
        """Exporta el audit log del usuario (GDPR).

        Con ``user_id`` la lectura es dual: cubre lo escrito bajo la clave del
        correo anterior y lo que los llamadores nuevos anotan ya por id.
        """
        with connect_read() as c:
            try:
                cur = c.execute(
                    f"SELECT * FROM audit_log WHERE {_IDENT} ORDER BY created_at DESC LIMIT 1000",  # SELECT *: export RGPD: la fila entera es el contrato
                    (user_id, user_key, user_id),
                )
                return rows_to_dicts(cur)
            except Exception:
                # Export GDPR: devolver [] ante un fallo entrega al usuario un
                # export incompleto que parece completo.
                log.warning("audit_export_by_user_key_failed", exc_info=True)
                return []

    def list_for_organization(
        self,
        organization_id: int,
        *,
        desde: str | None = None,
        hasta: str | None = None,
        cursor: tuple[str, int] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Rastro de una organización, del más reciente al más antiguo.

        ``audit_log`` no tiene columna de organización (no hay slot de
        migración): los eventos de organización se escriben con
        ``resource="org:<id>"`` dentro de ``detail`` (``shared/audit_events``)
        y aquí se recuperan con una regex anclada a la cabecera y a los
        separadores (:func:`patron_recurso_organizacion`), para que ``org:12`` no
        case con ``org:123`` ni un ``resource=org:12`` del payload cuente. Es un barrido por organización, no
        por usuario: quién puede pedirlo lo decide la ruta (owner/admin), y
        ``tests/test_user_key_sql_isolation.py`` lo documenta como tal.

        ``desde``/``hasta`` son ISO (``created_at`` es texto ISO en UTC, así
        que la comparación lexicográfica es la cronológica); ``hasta`` es
        exclusivo. ``cursor`` es ``(created_at, id)`` de la última fila vista.

        También casa ``resource="organization:<id>"``: es como escriben los
        pesos del go/no-go (``services/go_no_go_puntuacion.py``) y la propuesta
        de pesos aplicada (``services/pursuits.py``). Son configuración de la
        organización y quedaban fuera de su rastro; leer las dos formas recupera
        también lo ya persistido, que cambiar solo el escritor no arreglaría.
        """
        clausulas = ["detail ~ %s"]
        params: list[object] = [patron_recurso_organizacion(organization_id)]
        if desde:
            clausulas.append("created_at >= %s")
            params.append(desde)
        if hasta:
            clausulas.append("created_at < %s")
            params.append(hasta)
        if cursor is not None:
            clausulas.append("(created_at, id) < (%s, %s)")
            params.extend(cursor)
        params.append(limit)
        with connect_read() as c:
            # v129 añade ``user_id``; una base a medio migrar sigue sirviendo el
            # export con el actor derivado de la clave en texto.
            columna_actor = (
                "user_id" if "user_id" in get_table_columns(c, "audit_log") else ("NULL AS user_id")
            )
            cur = c.execute(
                f"SELECT id, user_key, {columna_actor}, action, detail, created_at "
                "FROM audit_log WHERE " + " AND ".join(clausulas) + " "
                "ORDER BY created_at DESC, id DESC LIMIT %s",
                params,
            )
            filas = rows_to_dicts(cur)
        return [_proyectar_entrada(fila) for fila in filas]
