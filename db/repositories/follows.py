"""Persistencia del seguimiento unificado (`follows`, ADR-031, v130).

Todo el SQL de `follows` vive aquí (ADR-022).

Dónde está el proyecto en el camino de ADR-031 §B
-------------------------------------------------
Fase **aditiva**, la primera de tres:

1. **Ahora.** `follows` existe, la rellenó el backfill de v130 y las tres
   tablas de origen la mantienen al día por escritura doble
   (`registrar` / `olvidar`, llamadas desde `watchlist_items`,
   `watchlist_empresas` y `radar_dismissals`). Las lecturas de esas tres
   pantallas **siguen leyendo de su tabla**: `follows` todavía no manda.
2. **Siguiente.** `scripts/check_follows_paridad.py` contra producción, con
   cero diferencias por usuario. Hasta que ese número sea cero, mover una
   lectura a `follows` es apostar el dato del cliente a que el backfill salió
   bien. El código de esa lectura ya está (ver «Lectura desde `follows`» más
   abajo), detrás de `FOLLOWS_LECTURA`, apagado: encenderlo es la fase 2.
3. **Después, por RFC y con fecha.** Retirada de los endpoints antiguos
   (`docs/rfc/2026-09-19-rfc-retirada-endpoints-watchlist.md`).

Lo que este módulo **sí** sirve hoy en producción es lo que antes no existía:
seguir órganos y CPV (que no tenían tabla) y la pregunta inversa —«¿quién
sigue esto?»— que ADR-031 §D le pide al despachador de eventos, y que con tres
tablas había que hacer tres veces.

Identidad dual
--------------
Mismo predicado que el resto de tablas de usuario tras v129 (ADR-030 fase 2):
la fila es tuya por `user_id`, o por `user_key` si el backfill no pudo
resolver el id. Una fila con OTRO id y tu misma clave no es tuya — es lo que
impide que quien registre mañana el correo que tú usabas herede lo que seguías.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

TargetType = Literal["licitacion", "lote", "empresa", "organo", "cpv"]
Kind = Literal["seguir", "descartar"]
Visibility = Literal["private", "organization"]

#: Enumeración cerrada de ADR-031 §A. Está aquí **y** en el `CHECK` de v130:
#: la base rechaza lo que no esté, y el DTO lo rechaza antes de llegar. Dos
#: copias de una lista de cinco valores es un precio razonable por un 422 en
#: vez de un 500.
TARGET_TYPES: frozenset[str] = frozenset({"licitacion", "lote", "empresa", "organo", "cpv"})
KINDS: frozenset[str] = frozenset({"seguir", "descartar"})

_COLS = (
    "id, organization_id, user_id, user_key, target_type, target_id, kind, "
    "visibility, channels_json, hasta, created_at"
)

#: Ver el docstring del módulo. Recibe siempre la terna `(user_id, user_key, user_id)`.
_IDENT = "(user_id = %s OR (user_key = %s AND (user_id IS NULL OR %s::int IS NULL)))"


def _fila(row: dict[str, Any]) -> dict[str, Any]:
    """Normaliza una fila para el DTO: fechas a ISO y `channels_json` a objeto."""
    salida = dict(row)
    for campo in ("created_at", "hasta"):
        valor = salida.get(campo)
        # `TIMESTAMPTZ` vuelve como `datetime`; el DTO lo quiere en ISO. El
        # `isinstance` y no un `hasattr` porque mypy no estrecha con lo segundo.
        if isinstance(valor, datetime):
            salida[campo] = valor.isoformat()
    crudo = salida.pop("channels_json", None)
    try:
        salida["channels"] = json.loads(crudo) if crudo else None
    except (TypeError, ValueError):
        # Un JSON corrupto no puede tumbar la lista de seguimientos de nadie.
        log.warning("follow_channels_json_invalido", follow_id=salida.get("id"))
        salida["channels"] = None
    return salida


def registrar(
    *,
    user_key: str,
    user_id: int | None,
    organization_id: int | None,
    target_type: str,
    target_id: str,
    kind: str = "seguir",
    visibility: str = "private",
    hasta: str | None = None,
) -> dict[str, Any] | None:
    """Da de alta un seguimiento; idempotente por `(usuario, objetivo, signo)`.

    Devuelve la fila resultante, sea la recién creada o la que ya estaba. El
    `DO UPDATE` no es un `DO NOTHING` a propósito: volver a descartar algo que
    ya descartaste con otra caducidad tiene que mover la caducidad, o el botón
    «posponer una semana» no haría nada la segunda vez.

    **No lanza.** Esto lo llaman las tres tablas de origen como escritura doble
    (ver el docstring del módulo): mientras `follows` sea una copia, un fallo
    aquí no puede tumbar el favorito que el usuario acaba de marcar. Cuando
    `follows` pase a ser la fuente de verdad, esta indulgencia se retira con la
    lectura.
    """
    if target_type not in TARGET_TYPES or kind not in KINDS:
        log.warning("follow_tipo_desconocido", target_type=target_type, kind=kind)
        return None
    try:
        with connect() as c:
            filas = rows_to_dicts(
                c.execute(
                    "INSERT INTO follows "
                    " (organization_id, user_id, user_key, target_type, target_id,"
                    "  kind, visibility, hasta) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT ON CONSTRAINT uq_follows_user_target DO UPDATE SET "
                    " organization_id = COALESCE(EXCLUDED.organization_id, follows.organization_id),"
                    " user_id = COALESCE(EXCLUDED.user_id, follows.user_id),"
                    " visibility = EXCLUDED.visibility,"
                    " hasta = EXCLUDED.hasta "
                    f"RETURNING {_COLS}",
                    (
                        organization_id,
                        user_id,
                        user_key,
                        target_type,
                        str(target_id),
                        kind,
                        visibility,
                        hasta,
                    ),
                )
            )
        return _fila(filas[0]) if filas else None
    except Exception as exc:
        log.warning(
            "follow_registrar_fallido",
            target_type=target_type,
            kind=kind,
            error=str(exc),
            exc_info=True,
        )
        return None


def olvidar(
    *,
    user_key: str,
    user_id: int | None,
    target_type: str,
    target_id: str,
    kind: str = "seguir",
) -> bool:
    """Borra un seguimiento propio. `True` si había algo que borrar.

    No acota por organización: se borra **lo tuyo**. Un seguimiento compartido
    lo ve toda la organización, pero la fila es de quien la creó, igual que la
    nota personal de un favorito (ADR-030 §D). No lanza, por lo mismo que
    `registrar`.
    """
    try:
        with connect() as c:
            cur = c.execute(
                "DELETE FROM follows WHERE target_type = %s AND target_id = %s "
                f"AND kind = %s AND {_IDENT}",
                (target_type, str(target_id), kind, user_id, user_key, user_id),
            )
            return bool(cur.rowcount > 0)
    except Exception as exc:
        log.warning("follow_olvidar_fallido", target_type=target_type, error=str(exc))
        return False


def listar(
    *,
    user_key: str,
    user_id: int | None,
    organization_id: int | None = None,
    target_type: str | None = None,
    kind: str = "seguir",
    vigentes: bool = True,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Seguimientos del usuario, y los compartidos de su organización.

    `vigentes` descarta los que ya caducaron (`hasta` en el pasado): un
    descarte pospuesto una semana **es** un seguimiento vencido, no uno
    borrado, y la fila se conserva para poder decir «lo descartaste el día X».
    Pedir `vigentes=False` es lo que quiere la auditoría, no la interfaz.
    """
    condiciones = [f"({_IDENT} OR (organization_id = %s AND visibility = 'organization'))"]
    params: list[Any] = [user_id, user_key, user_id, organization_id]
    condiciones.append("kind = %s")
    params.append(kind)
    if target_type is not None:
        condiciones.append("target_type = %s")
        params.append(target_type)
    if vigentes:
        condiciones.append("(hasta IS NULL OR hasta > now())")
    params.append(max(1, min(int(limit), 5000)))

    with connect_read() as c:
        filas = rows_to_dicts(
            c.execute(
                f"SELECT {_COLS} FROM follows WHERE {' AND '.join(condiciones)} "
                "ORDER BY created_at DESC, id DESC LIMIT %s",
                tuple(params),
            )
        )
    return [_fila(f) for f in filas]


def seguidores(target_type: str, target_id: str, *, kind: str = "seguir") -> list[dict[str, Any]]:
    """Quién sigue este objetivo (ADR-031 §D).

    La pregunta del despachador de eventos, y la razón de ser del índice
    `idx_follows_target`. Con las tres tablas antiguas había que hacerla tres
    veces y unir a mano; con un `target_type` nuevo, cuatro.

    Deliberadamente **sin** ámbito de organización: el despachador corre fuera
    de una petición y tiene que ver a todo el mundo que sigue algo, no a los de
    un tenant. El paso franco de las políticas de v128 lo permite justamente
    para este caso.
    """
    with connect_read() as c:
        filas = rows_to_dicts(
            c.execute(
                f"SELECT {_COLS} FROM follows "
                "WHERE target_type = %s AND target_id = %s AND kind = %s "
                "AND (hasta IS NULL OR hasta > now()) "
                "ORDER BY id",
                (target_type, str(target_id), kind),
            )
        )
    return [_fila(f) for f in filas]


# ── Lectura desde `follows` (ADR-031 §B, fase 2) ────────────────────────────
#
# Detrás de `FOLLOWS_LECTURA` (apagado por defecto). Con el flag encendido, las
# tres pantallas antiguas —favoritos, empresas vigiladas y descartes del
# Radar— siguen llamando a sus endpoints de siempre, pero **qué** sigue el
# usuario lo decide `follows`; la tabla de origen sólo aporta las columnas que
# `follows` no tiene (la nota del favorito, el correo y la frecuencia de la
# alerta de empresa, la acción y el score del descarte). Por eso el cruce con
# ella es un `LEFT JOIN`: si una fila falta en origen, el seguimiento se ve
# igual, con esas columnas vacías — que es exactamente lo que habrá el día que
# la tabla de origen se retire (ver `docs/rfc/2026-09-19-rfc-retirada-endpoints-watchlist.md`).
#
# Cada función devuelve la MISMA forma que su gemela antigua, clave a clave,
# para que la ruta no tenga que saber de dónde leyó. Lo fija
# `tests/test_follows_lectura.py`.


def lectura_desde_follows() -> bool:
    """Valor vigente de ``settings.FOLLOWS_LECTURA``.

    Importación diferida, igual que ``db.sql_fragments.lectura_tipada_activa``:
    el flag se lee en cada llamada para que la vuelta atrás sea un cambio de
    configuración y no un despliegue.
    """
    from config import settings

    return bool(settings.FOLLOWS_LECTURA)


def _iso(valor: Any) -> Any:
    return valor.isoformat() if isinstance(valor, datetime) else valor


def favoritos_desde_follows(
    user_key: str, organization_id: int, user_id: int | None = None
) -> list[dict[str, Any]]:
    """Forma de ``WatchlistRepository.list_items``, con la pertenencia de ``follows``.

    Mismo ámbito que la gemela: la organización activa, y dentro de ella lo
    compartido o lo propio (identidad dual). ``id`` es el del favorito de
    origen si existe; si no, el de ``follows`` —el DTO lo exige entero y el
    frontend sólo lo usa como clave de fila—.
    """
    with connect_read() as c:
        return rows_to_dicts(
            c.execute(
                "SELECT COALESCE(wi.id, f.id) AS id, f.target_id AS id_externo, "
                "       f.created_at, f.organization_id, f.visibility, wi.nota, "
                "       l.titulo, l.importe, l.estado, l.fecha_publicacion "
                "FROM follows f "
                "LEFT JOIN watchlist_items wi "
                "  ON wi.id_externo = f.target_id AND wi.user_key = f.user_key "
                "LEFT JOIN licitaciones l ON l.id_externo = f.target_id "
                "WHERE f.target_type = 'licitacion' AND f.kind = 'seguir' "
                "AND f.organization_id = %s AND (f.visibility = 'organization' OR "
                "(f.user_id = %s OR (f.user_key = %s AND (f.user_id IS NULL OR %s::int IS NULL)))) "
                "ORDER BY f.created_at DESC, f.id DESC",
                (organization_id, user_id, user_key, user_id),
            )
        )


def empresas_desde_follows(
    user_key: str, organization_id: int, *, user_id: int | None = None
) -> list[dict[str, Any]]:
    """Forma de ``db.watchlist_empresas.list_entries``, con la pertenencia de ``follows``.

    ``target_id`` es texto (el objetivo es polimórfico); se compara contra
    ``empresa_id::text`` y no al revés para que un ``target_id`` que no sea un
    entero no tumbe la consulta con un error de cast. Las fechas salen en ISO:
    el DTO de la ruta las declara ``str``.
    """
    with connect_read() as c:
        filas = rows_to_dicts(
            c.execute(
                "SELECT COALESCE(w.id, f.id) AS id, e.empresa_id, e.nombre_canonico, "
                "       e.nif_canonico, w.email, w.frequency, f.created_at, "
                "       w.last_notified_at, f.organization_id, f.visibility "
                "FROM follows f "
                "JOIN empresas e ON e.empresa_id::text = f.target_id "
                "LEFT JOIN watchlist_empresas w "
                "  ON w.empresa_id = e.empresa_id AND w.user_key = f.user_key "
                " AND w.organization_id = f.organization_id "
                "WHERE f.target_type = 'empresa' AND f.kind = 'seguir' "
                "AND f.organization_id = %s AND (f.visibility = 'organization' OR "
                "(f.user_id = %s OR (f.user_key = %s AND (f.user_id IS NULL OR %s::int IS NULL)))) "
                "ORDER BY e.nombre_canonico",
                (organization_id, user_id, user_key, user_id),
            )
        )
    return [{**f, "created_at": _iso(f["created_at"])} for f in filas]


def descartes_desde_follows(user_key: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
    """Forma de ``db.radar_dismissals.list_detalle``, con la pertenencia de ``follows``.

    Vigencia y caducidad (``hasta``) salen de ``follows``; ``accion``,
    ``score`` y ``banda`` del descarte de origen más reciente, que es lo que
    ``follows`` no guarda. ``DISTINCT ON`` por lo mismo que la gemela: dos
    claves de un mismo usuario (antes de v129) son dos filas y un descarte.
    Recientes primero.
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT DISTINCT ON (f.target_id) f.target_id, f.hasta, rd.accion, rd.score, "
            "       rd.banda, f.created_at "
            "FROM follows f "
            "LEFT JOIN LATERAL ("
            "  SELECT accion, score, banda FROM radar_dismissals "
            "  WHERE id_externo = f.target_id AND user_key = f.user_key "
            "  ORDER BY created_at DESC LIMIT 1"
            ") rd ON TRUE "
            "WHERE f.target_type = 'licitacion' AND f.kind = 'descartar' "
            "AND (f.hasta IS NULL OR f.hasta > now()) "
            "AND (f.user_id = %s OR (f.user_key = %s AND (f.user_id IS NULL OR %s::int IS NULL))) "
            "ORDER BY f.target_id, f.created_at DESC",
            (user_id, user_key, user_id),
        )
        filas = sorted(cur.fetchall(), key=lambda row: row[5], reverse=True)
    return [
        {
            "id_externo": str(row[0]),
            "hasta": row[1].isoformat() if row[1] is not None else None,
            "accion": row[2],
            "score": row[3],
            "banda": row[4],
        }
        for row in filas
    ]


def contar_por_tipo() -> dict[str, int]:
    """`{target_type:kind: filas}`. Lo usa el script de paridad y el panel de calidad."""
    with connect_read() as c:
        filas = c.execute(
            "SELECT target_type, kind, COUNT(*) FROM follows GROUP BY target_type, kind"
        ).fetchall()
    return {f"{r[0]}:{r[1]}": int(r[2]) for r in filas}


def borrar_de_usuario(user_key: str, *, user_id: int | None = None) -> int:
    """Borra todos los seguimientos del usuario. Lo llama el borrado GDPR."""
    with connect() as c:
        cur = c.execute(
            f"DELETE FROM follows WHERE {_IDENT}",
            (user_id, user_key, user_id),
        )
        return int(cur.rowcount or 0)


def exportar_de_usuario(user_key: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
    """Seguimientos del usuario para el export de datos personales (GDPR)."""
    with connect_read() as c:
        filas = rows_to_dicts(
            c.execute(
                f"SELECT {_COLS} FROM follows WHERE {_IDENT} ORDER BY id LIMIT 5000",
                (user_id, user_key, user_id),
            )
        )
    return [_fila(f) for f in filas]


# ── Paridad con las tablas de origen (ADR-031 §B) ───────────────────────────
#
# El SQL vive aquí y no en `scripts/` porque ahí está prohibido (ADR-022,
# TID251). El script `scripts/check_follows_paridad.py` es la presentación.

#: `(tabla de origen, expresión del target_id, target_type, kind)`. Es la MISMA
#: proyección que hace el backfill de v130; si una de las dos cambia sin la
#: otra, la paridad mide otra cosa y deja de servir para decidir nada.
PARES_DE_ORIGEN: tuple[tuple[str, str, str, str], ...] = (
    ("watchlist_items", "id_externo", "licitacion", "seguir"),
    ("watchlist_empresas", "empresa_id::text", "empresa", "seguir"),
    ("radar_dismissals", "id_externo", "licitacion", "descartar"),
)


def paridad_con_origen(
    tabla: str, target_expr: str, target_type: str, kind: str, *, ejemplos: int = 5
) -> dict[str, Any]:
    """Compara una tabla de origen con su proyección en ``follows``.

    Devuelve filas de cada lado, cuántas faltan y cuántas sobran, y hasta
    ``ejemplos`` de cada clase. ``EXCEPT`` y no un ``LEFT JOIN ... IS NULL``: la
    comparación es sobre la tupla entera (usuario + objetivo), y ``EXCEPT`` la
    escribe una vez en vez de repetir la condición con sus NULLs.

    Los literales que se interpolan salen de :data:`PARES_DE_ORIGEN`, nunca de
    entrada externa.
    """
    origen = f"SELECT user_key, {target_expr} AS target_id FROM {tabla}"
    destino = (
        "SELECT user_key, target_id FROM follows "
        f"WHERE target_type = '{target_type}' AND kind = '{kind}'"
    )
    vacio: dict[str, Any] = {
        "tabla": tabla,
        "target_type": target_type,
        "kind": kind,
        "filas_origen": 0,
        "filas_follows": 0,
        "faltan": [],
        "sobran": [],
    }

    with connect_read() as c:
        existe = c.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = %s",
            (tabla,),
        ).fetchone()
        if existe is None:
            return vacio

        filas_origen = int(c.execute(f"SELECT COUNT(*) FROM ({origen}) o").fetchone()[0])
        filas_follows = int(c.execute(f"SELECT COUNT(*) FROM ({destino}) f").fetchone()[0])
        faltan = c.execute(f"{origen} EXCEPT {destino}").fetchall()
        sobran = c.execute(f"{destino} EXCEPT {origen}").fetchall()

    return {
        "tabla": tabla,
        "target_type": target_type,
        "kind": kind,
        "filas_origen": filas_origen,
        "filas_follows": filas_follows,
        "faltan": [(str(r[0]), str(r[1])) for r in faltan],
        "sobran": [(str(r[0]), str(r[1])) for r in sobran],
    }
