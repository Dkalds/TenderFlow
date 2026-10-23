"""Cuántas canónicas cambiarían de fila con el criterio vigente (solo lectura).

La revisión ``v157`` cambia el primer criterio de canónica de la vista
``licitaciones_canonicas``: de ``fuente <> 'placsp'`` (``v102``) a
:func:`db.sql_fragments.rango_de_fuente_sql` (PLACSP con el bulk → resto →
TED). El conjunto publicable no cambia, pero **qué fila** representa a cada
contrato sí, y con ella su URL en el sitemap. Esto lo mide sobre la tabla viva
antes de aplicar la revisión: agrupa las filas publicables por la clave de la
vista y elige la canónica con los dos órdenes, sin tocar la vista ni escribir
nada.

Se calcula sobre ``licitaciones`` y no contra la vista porque así responde lo
mismo antes y después de aplicar ``v157``, y porque la vista puede llevar hasta
un ciclo de ingesta de retraso.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from db.database import connect_read
from db.repositories.publico import _BASE_WHERE
from db.sql_fragments import clave_canonica_agrupable_sql, orden_canonico_sql, rango_de_fuente_sql

#: Primer criterio de ``v102``, el que ``v157`` sustituye.
CRITERIO_V102 = "(l.fuente <> 'placsp')"


def orden_v102_sql() -> str:
    """El ``ORDER BY`` de canónica de ``v102``: el vigente con el primer criterio viejo.

    Se deriva del vigente en vez de copiarse para que los desempates (fecha de
    publicación, primera extracción, id) sean **los mismos** por construcción:
    el delta tiene que medir solo el cambio de fuente.
    """
    vigente = orden_canonico_sql("l")
    rango = rango_de_fuente_sql("l")
    if not vigente.startswith(rango):
        raise RuntimeError("el orden de canónica ya no empieza por el rango de fuente")
    return CRITERIO_V102 + vigente[len(rango) :]


def _sql_delta() -> str:
    clave = clave_canonica_agrupable_sql("l")
    # Todas las piezas son constantes del repositorio: no hay entrada de nadie.
    return (
        "WITH p AS ("
        f"  SELECT l.id_externo, l.fuente, {clave} AS k, "
        f"    row_number() OVER (PARTITION BY {clave} ORDER BY {orden_v102_sql()}) AS rn_antes, "
        f"    row_number() OVER (PARTITION BY {clave} ORDER BY {orden_canonico_sql('l')}) "
        "      AS rn_despues "
        f"  FROM licitaciones l WHERE {_BASE_WHERE}"
        "), antes AS (SELECT k, id_externo, fuente FROM p WHERE rn_antes = 1), "
        "despues AS (SELECT k, id_externo, fuente FROM p WHERE rn_despues = 1) "
        "SELECT a.id_externo, a.fuente, d.id_externo, d.fuente "
        "FROM antes a JOIN despues d USING (k) "
        "WHERE a.id_externo <> d.id_externo "
        "ORDER BY a.fuente, d.fuente, a.id_externo"
    )


def _sql_contratos() -> str:
    clave = clave_canonica_agrupable_sql("l")
    return f"SELECT count(DISTINCT {clave}) FROM licitaciones l WHERE {_BASE_WHERE}"


@dataclass(frozen=True)
class CambioCanonica:
    """Un contrato cuya fila canónica cambia: de ``antes`` (v102) a ``despues`` (v157)."""

    antes: str
    fuente_antes: str | None
    despues: str
    fuente_despues: str | None


@dataclass
class DeltaCanonicas:
    contratos: int
    cambios: list[CambioCanonica] = field(default_factory=list)

    def por_transicion(self) -> dict[str, int]:
        """``"ted → pscp": n``: de qué fuente a qué fuente pasa la canónica."""
        conteo: dict[str, int] = {}
        for c in self.cambios:
            clave = f"{c.fuente_antes} → {c.fuente_despues}"
            conteo[clave] = conteo.get(clave, 0) + 1
        return dict(sorted(conteo.items(), key=lambda kv: (-kv[1], kv[0])))


def medir_delta() -> DeltaCanonicas:
    """Contratos publicables y los que cambiarían de canónica. No escribe nada.

    Recorre y ordena dos veces las filas publicables, lo mismo que cuesta
    construir la vista: segundos en producción, dentro del ``statement_timeout``
    del pool de lectura.
    """
    with connect_read() as c:
        fila = c.execute(_sql_contratos()).fetchone()
        filas = c.execute(_sql_delta()).fetchall()
    return DeltaCanonicas(
        contratos=int(fila[0]) if fila else 0,
        cambios=[
            CambioCanonica(
                antes=str(r[0]),
                fuente_antes=None if r[1] is None else str(r[1]),
                despues=str(r[2]),
                fuente_despues=None if r[3] is None else str(r[3]),
            )
            for r in filas
        ],
    )
