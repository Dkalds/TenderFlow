"""Diccionario de tecnologías como dato (C5.6, D28, v125).

El criterio —qué diccionario está vigente, cuándo se cae a la semilla, cómo se
mide el impacto de una keyword— vive en `services/tecnologias_diccionario.py`.
Aquí solo está el SQL.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

#: Ventana del preview de impacto, en días.
#:
#: Noventa, como pide el ítem: suficiente para que un término estacional
#: aparezca y corto para que la consulta no recorra el corpus entero — que son
#: 700 000 filas y una pantalla de `/ops` no puede pagar eso.
VENTANA_IMPACTO_DIAS = 90


class TecnologiasKeywordsRepository:
    """Acceso a ``tecnologias_keywords``."""

    def listar(self, *, incluir_inactivas: bool = False) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, tecnologia, keyword, activa, origen, created_by_user_id, "
            "created_at, updated_at FROM tecnologias_keywords "
        )
        if not incluir_inactivas:
            sql += "WHERE activa "
        sql += "ORDER BY tecnologia, lower(keyword)"
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql))

    def diccionario_activo(self) -> dict[str, list[str]]:
        """`{tecnologia: [keywords]}` de las filas activas.

        Devuelve `{}` cuando la tabla está vacía **o no existe**: las dos son
        «no hay diccionario en base de datos», y el servicio cae a la semilla.
        Distinguirlas obligaría a cada llamante a tratar un caso que resuelve
        igual.
        """
        try:
            filas = self.listar()
        except Exception:
            log.warning("tecnologias_keywords_lectura_fallida", exc_info=True)
            return {}
        salida: dict[str, list[str]] = {}
        for f in filas:
            salida.setdefault(str(f["tecnologia"]), []).append(str(f["keyword"]))
        return salida

    def upsert(
        self,
        *,
        tecnologia: str,
        keyword: str,
        activa: bool = True,
        origen: str = "manual",
        user_id: int | None = None,
    ) -> bool:
        """Alta o reactivación de una keyword. `True` si la fila cambió.

        `ON CONFLICT` sobre `(tecnologia, lower(keyword))`: reañadir una keyword
        desactivada la reactiva en vez de fallar, que es lo que quien la escribe
        espera. **El `origen` no se pisa** al reactivar: una keyword que vino de
        la semilla sigue siendo de la semilla aunque alguien la reactive a mano,
        o una resiembra dejaría de reconocerla como suya.
        """
        ahora = now_utc_iso()
        with connect() as c:
            cur = c.execute(
                "INSERT INTO tecnologias_keywords "
                "(tecnologia, keyword, activa, origen, created_by_user_id, "
                " created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tecnologia, lower(keyword)) DO UPDATE SET "
                "activa = excluded.activa, updated_at = excluded.updated_at",
                (tecnologia, keyword, activa, origen, user_id, ahora, ahora),
            )
            return bool(getattr(cur, "rowcount", 0))

    def desactivar(self, *, tecnologia: str, keyword: str) -> bool:
        """Retira una keyword sin borrar la fila.

        Con `DELETE`, «esta keyword se quitó el martes» dejaría de ser una
        pregunta contestable, y retirar un término es una decisión tan revisable
        como añadirlo.
        """
        with connect() as c:
            cur = c.execute(
                "UPDATE tecnologias_keywords SET activa = false, updated_at = %s "
                "WHERE tecnologia = %s AND lower(keyword) = lower(%s) AND activa",
                (now_utc_iso(), tecnologia, keyword),
            )
            return bool(getattr(cur, "rowcount", 0))

    def sembrar(self, semilla: dict[str, list[str]]) -> int:
        """Inserta las keywords de la semilla que falten. Idempotente.

        `ON CONFLICT DO NOTHING`: una keyword que alguien desactivó a mano **no
        se reactiva** al resembrar. Si lo hiciera, cada despliegue desharía en
        silencio una decisión del equipo, y la tabla dejaría de gobernar.
        """
        ahora = now_utc_iso()
        filas = [
            (tec, kw, True, "semilla", None, ahora, ahora)
            for tec, kws in semilla.items()
            for kw in kws
        ]
        if not filas:
            return 0
        with connect() as c:
            cur = c.executemany(
                "INSERT INTO tecnologias_keywords "
                "(tecnologia, keyword, activa, origen, created_by_user_id, "
                " created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tecnologia, lower(keyword)) DO NOTHING",
                filas,
            )
            return int(getattr(cur, "rowcount", 0) or 0)

    def impacto(self, keyword: str, *, dias: int = VENTANA_IMPACTO_DIAS) -> dict[str, Any]:
        """Cuántos expedientes **nuevos** traería una keyword (preview de D28).

        «Nuevos» es la palabra que hace útil el número: se cuentan solo los que
        casan con la keyword y **no tienen ya tecnología asignada**. Contar
        todos los que la mencionan daría cifras enormes y sin significado —«SAP»
        aparece en miles de expedientes que ya están dentro—, y quien decide
        necesita saber qué *añade*, no qué toca.

        Se usa `ILIKE '% keyword %'` con separadores en vez de `~*` con
        `\\y`: el operador de regex de Postgres no puede usar el índice de
        trigramas de `pg_trgm`, y esta consulta la dispara una pantalla.
        """
        patron = f"%{keyword.strip()}%"
        with connect_read() as c:
            fila = c.execute(
                "SELECT COUNT(*) AS nuevos FROM licitaciones "
                "WHERE fecha_publicacion >= (CURRENT_DATE - CAST(%s AS INTEGER))::text "
                "  AND tecnologia IS NULL "
                "  AND (titulo ILIKE %s OR descripcion ILIKE %s)",
                (int(dias), patron, patron),
            ).fetchone()
        return {
            "keyword": keyword,
            "dias": int(dias),
            "expedientes_nuevos": int(fila[0]) if fila else 0,
        }
