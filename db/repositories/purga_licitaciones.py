"""SQL de la purga de licitaciones fuera del universo tecnológico de una fuente.

Lo usa `scripts/purgar_pscp_sin_tecnologia.py`. El criterio —qué fila es
tecnología— no vive aquí: lo decide `scraper.connectors.pscp.senal_tecnologica`
en Python, fila a fila, porque es la misma puerta que aplica el conector y el
diccionario es un regex que Postgres no puede evaluar igual (ADR-022 pide el SQL
en `db/`, no la regla de negocio).

Qué es «trabajo de usuario» y qué es basura
-------------------------------------------
Una licitación que no pasa la puerta se borra **salvo** que alguien haya
trabajado sobre ella: esas se conservan y se cuentan aparte, porque borrarlas
rompería el pipeline, la cartera o el seguimiento de un cliente por una
decisión de ingesta. Las tablas de :data:`_REFERENCIAS_PROTECTORAS` son las
que representan ese trabajo.

Las referencias blandas —sin FK— a una fila borrada se borran con ella
(:data:`_REFERENCIAS_ARRASTRADAS`): una notificación que abre un expediente que
ya no existe, un resumen por correo pendiente de enviarlo o un descarte del
Radar sobre él no son dato, son restos. Las referencias con FK se van por el
`ON DELETE CASCADE` de su propia tabla (adjudicaciones, historial, eventos,
scores, duplicados…).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

#: `(tabla, columna, condición extra)` de las referencias que **protegen** una
#: licitación de la purga. `resoluciones_recurso` no es trabajo de usuario pero
#: su FK no tiene `ON DELETE`, así que borrar la licitación fallaría: se
#: conserva y se cuenta como las demás.
_REFERENCIAS_PROTECTORAS: tuple[tuple[str, str, str], ...] = (
    ("pursuits", "licitacion_id", ""),
    ("contratos_cartera", "licitacion_id", ""),
    ("watchlist_items", "id_externo", ""),
    ("follows", "target_id", "AND target_type = 'licitacion' AND kind = 'seguir'"),
    ("etiquetas_aplicadas", "objeto_id", ""),
    ("organization_references", "expediente_id", ""),
    ("resoluciones_recurso", "licitacion_id", ""),
)

#: Referencias sin FK que se borran junto con la licitación. Los descartes van
#: en las dos tablas (`follows` y la legada `radar_dismissals`) para que
#: `scripts/check_follows_paridad.py` siga viéndolas iguales.
_REFERENCIAS_ARRASTRADAS: tuple[tuple[str, str, str], ...] = (
    ("user_notifications", "licitacion_id", ""),
    ("pending_digests", "licitacion_id", ""),
    ("follows", "target_id", "AND target_type = 'licitacion' AND kind = 'descartar'"),
    ("radar_dismissals", "id_externo", ""),
)


def lote_de_fuente(fuente: str, *, despues_de: str, limite: int) -> list[dict[str, Any]]:
    """Siguiente lote de filas de ``fuente``, en orden de ``id_externo``.

    Paginación por clave y no por `OFFSET`: el recorrido cubre cientos de miles
    de filas y la purga las va borrando mientras avanza, así que un desplazamiento
    se saltaría filas. Con ``id_externo > despues_de`` cada lote empieza donde
    acabó el anterior, haya borrado lo que haya borrado.
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT id_externo, titulo, cpv, tecnologia, raw_keywords, analysis_universe "
            "FROM licitaciones "
            "WHERE fuente = %s AND id_externo > %s "
            "ORDER BY id_externo "
            "LIMIT %s",
            (fuente, despues_de, limite),
        )
        return rows_to_dicts(cur)


def _protegidas(c: Any, ids: Sequence[str]) -> set[str]:
    protegidas: set[str] = set()
    for tabla, columna, extra in _REFERENCIAS_PROTECTORAS:
        # Tabla, columna y condición son constantes de este módulo, nunca entrada.
        filas = c.execute(
            f"SELECT DISTINCT {columna} FROM {tabla} WHERE {columna} = ANY(%s) {extra}",
            (list(ids),),
        ).fetchall()
        protegidas.update(str(f[0]) for f in filas)
    return protegidas


def ids_protegidos(ids: Sequence[str]) -> set[str]:
    """Los ``ids`` sobre los que hay trabajo de usuario (no se purgan)."""
    if not ids:
        return set()
    with connect_read() as c:
        return _protegidas(c, ids)


def purgar(ids: Sequence[str], *, fuente: str) -> dict[str, int]:
    """Borra las licitaciones ``ids`` de ``fuente`` que nadie esté usando.

    Todo en una transacción: las protegidas se recalculan **dentro** de ella, así
    que una oportunidad creada entre el dry-run y este lote no se pierde. El
    filtro por ``fuente`` es un seguro: aunque el llamante se equivoque de ids,
    esto no puede borrar una fila de otra fuente ni nada que cuelgue de ella.

    Devuelve, por tabla, cuántas filas se borraron (``licitaciones`` y las
    referencias blandas que se fueron con ellas) y cuántas licitaciones se
    conservaron por estar protegidas (``protegidas``).
    """
    resumen: dict[str, int] = {"licitaciones": 0, "protegidas": 0}
    if not ids:
        return resumen
    with connect() as c:
        # Primero, cuáles son de verdad de esta fuente: las referencias blandas
        # se borran por id, y un id de otra fuente colado en la lista se
        # llevaría las notificaciones de una fila que no se va a borrar.
        de_la_fuente = {
            str(f[0])
            for f in c.execute(
                "SELECT id_externo FROM licitaciones WHERE id_externo = ANY(%s) AND fuente = %s",
                (list(ids), fuente),
            ).fetchall()
        }
        protegidas = _protegidas(c, sorted(de_la_fuente))
        borrables = sorted(de_la_fuente - protegidas)
        resumen["protegidas"] = len(protegidas)
        if not borrables:
            return resumen
        for tabla, columna, extra in _REFERENCIAS_ARRASTRADAS:
            n = c.execute(
                f"DELETE FROM {tabla} WHERE {columna} = ANY(%s) {extra}",
                (borrables,),
            ).rowcount
            clave = f"{tabla}_descartes" if "descartar" in extra else tabla
            resumen[clave] = resumen.get(clave, 0) + max(n, 0)
        resumen["licitaciones"] = max(
            c.execute(
                "DELETE FROM licitaciones WHERE id_externo = ANY(%s) AND fuente = %s",
                (borrables, fuente),
            ).rowcount,
            0,
        )
    return resumen


def contar_de_fuente(fuente: str) -> dict[str, int]:
    """Fotografía de la fuente: filas totales y cuántas llevan `tecnologia`."""
    with connect_read() as c:
        fila = c.execute(
            "SELECT COUNT(*), "
            "  COUNT(*) FILTER (WHERE tecnologia IS NOT NULL AND tecnologia <> '') "
            "FROM licitaciones WHERE fuente = %s",
            (fuente,),
        ).fetchone()
    total = int(fila[0] or 0) if fila else 0
    con_tecnologia = int(fila[1] or 0) if fila else 0
    return {"total": total, "con_tecnologia": con_tecnologia}
