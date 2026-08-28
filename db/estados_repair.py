"""Reparación del campo ``licitaciones.estado`` para filas ya escritas.

Existe por el fallback que tenía ``scraper/connectors/pscp.py::_fase_to_estado``
hasta 2026-08-27: cuando no reconocía una fase catalana, escribía el texto crudo
de la fuente en mayúsculas y **truncado a 20 caracteres**. De ahí salieron los
valores que ``GET /meta/filters`` ofrecía como si fueran opciones legítimas de
filtro ("PUBLICACIÓ AGREGADA ", "EXPEDIENT EN AVALUAC", "EXECUCIÓ"), y de ahí
que "Total activas" contara 657.158 expedientes: sin código canónico, ``estado``
no está en ``ESTADOS_CERRADOS`` y :func:`shared.estados.abierta_sql` lo cuenta
como abierto — que es el comportamiento correcto para un estado desconocido, y
por eso el arreglo va en el dato y no en el predicado.

El conector ya no ensucia más filas. Este módulo limpia las que quedaron.

Por qué está aquí y no en el script
-----------------------------------
``scripts/repair_estados_pscp.py`` es quien decide *qué* reparar (reusa la tabla
de mapeo del conector para no mantener un mapeo paralelo) y quien pide
confirmación. Pero no puede llevar SQL ni abrir conexión: ADR-022 pone todo el
SQL en ``db/``, y la whitelist TID251 de ``pyproject.toml`` está congelada — sólo
se le quitan líneas. Así que el script trae el criterio y este módulo, las dos
únicas operaciones de base de datos que ese criterio necesita.

Por qué el UPDATE va por lotes
------------------------------
El caso real es de 1,3 millones de filas en un solo valor ("PUBLICACIÓ
AGREGADA "). Un ``UPDATE`` único sobre eso mantiene una transacción abierta
durante minutos, genera un WAL enorme y bloquea el ``autovacuum`` de la tabla
que alimenta el Radar. Por lotes, cada uno confirma por su cuenta: la
reparación es interrumpible y reanudable, y lo peor que puede pasar si se corta
es que quede a medias — que es exactamente el estado del que se parte, no uno
peor.

El bucle termina solo: cada lote deja de cumplir el ``WHERE`` que lo seleccionó.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read

__all__ = ["contar_estados_por_fuente", "reescribir_estado"]

#: Filas por lote del UPDATE. 5.000 mantiene cada transacción por debajo del
#: segundo en la instancia de producción sin convertir 1,3M de filas en 260
#: viajes innecesarios.
_TAMANO_LOTE = 5_000


def contar_estados_por_fuente(fuente: str) -> dict[str | None, int]:
    """Reparto de filas por valor de ``estado`` para una fuente.

    Es la fotografía de la que sale el plan de reparación, y también lo que hace
    que el ``--dry-run`` del script diga algo verdadero: el conteo viene de la
    base, no de una estimación.

    ``NULL`` se conserva como clave ``None`` en vez de agruparse con el resto:
    una fila sin estado es un caso distinto de una con estado sucio, y el
    llamante decide qué hacer con cada uno.
    """
    with connect_read() as c:
        filas = c.execute(
            "SELECT estado, COUNT(*) FROM licitaciones WHERE fuente = %s GROUP BY estado",
            (fuente,),
        ).fetchall()
    return {(fila[0] if fila[0] is None else str(fila[0])): int(fila[1]) for fila in filas}


def reescribir_estado(fuente: str, *, actual: str, nuevo: str | None) -> int:
    """Cambia ``estado`` de ``actual`` a ``nuevo`` en una fuente. Devuelve filas tocadas.

    ``nuevo=None`` pone la columna a ``NULL``, que es lo que corresponde a una
    fase que nadie ha mapeado todavía: sin código no hay evidencia de cierre y
    la fila vuelve a contar como abierta, que es el fallo barato de los dos (el
    caro es que un expediente vivo desaparezca del Radar en silencio).

    Idempotente: reejecutarlo no toca nada porque ya no quedan filas con
    ``estado = actual``.

    Se niega a ejecutarse si ``actual`` y ``nuevo`` coinciden. No es una
    comprobación defensiva de adorno: el ``WHERE`` del lote selecciona por
    ``estado = actual`` y el ``SET`` lo deja igual, así que el mismo lote
    volvería a salir elegido en cada vuelta y el bucle no terminaría nunca.
    """
    if actual == nuevo:
        raise ValueError(
            f"reescribir_estado: 'actual' y 'nuevo' son el mismo valor ({actual!r}); "
            "el bucle por lotes no terminaría"
        )

    # `ctid` en vez de una clave primaria: es el identificador físico de fila de
    # Postgres, siempre está disponible y no obliga a este módulo a saber cuál
    # es la clave de `licitaciones`. Se recalcula en cada vuelta, así que las
    # filas que el UPDATE anterior movió no se vuelven a seleccionar.
    sql = (
        "UPDATE licitaciones SET estado = %s WHERE ctid IN ("
        "  SELECT ctid FROM licitaciones WHERE fuente = %s AND estado = %s LIMIT %s"
        ")"
    )

    total = 0
    while True:
        with connect() as c:
            cursor: Any = c.execute(sql, (nuevo, fuente, actual, _TAMANO_LOTE))
            tocadas = int(cursor.rowcount or 0)
        total += tocadas
        if tocadas < _TAMANO_LOTE:
            # Último lote (o ninguno): no quedan filas que cumplan el WHERE.
            return total
