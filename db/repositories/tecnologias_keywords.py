"""Diccionario de tecnologías como dato (C5.6, D28).

El esquema lo crea ``v126``, y su docstring explica por qué una fila por keyword
y por qué las retiradas se desactivan en vez de borrarse.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)


class TecnologiaKeywordRepository:
    """Acceso a ``tecnologias_keywords``."""

    def cargar_activas(self) -> dict[str, list[str]]:
        """``{tecnologia: [keywords]}`` con lo que está activo.

        Devuelve ``{}`` si la tabla está vacía o no existe todavía. El llamante
        distingue eso de «no filtres nada» — ver ``services/tech_dictionary.py``.
        """
        with connect_read() as c:
            filas = rows_to_dicts(
                c.execute(
                    "SELECT tecnologia, keyword FROM tecnologias_keywords "
                    "WHERE activa ORDER BY tecnologia, keyword"
                )
            )
        salida: dict[str, list[str]] = {}
        for fila in filas:
            salida.setdefault(str(fila["tecnologia"]), []).append(str(fila["keyword"]))
        return salida

    def listar(self, *, tecnologia: str | None = None) -> list[dict[str, Any]]:
        """Todas las keywords, activas y retiradas, para el panel de ``/ops``."""
        sql = (
            "SELECT id, tecnologia, keyword, activa, created_at, updated_at "
            "FROM tecnologias_keywords "
        )
        params: list[Any] = []
        if tecnologia:
            sql += "WHERE tecnologia = %s "
            params.append(tecnologia)
        sql += "ORDER BY tecnologia, activa DESC, keyword"
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def sembrar(self, diccionario: dict[str, list[str]]) -> int:
        """Inserta la semilla sin pisar lo que ya haya. Devuelve las filas nuevas.

        Idempotente por el único ``(tecnologia, lower(keyword))``: correrla dos
        veces no duplica, y **no reactiva** una keyword que alguien retiró a
        propósito — ``DO NOTHING`` y no ``DO UPDATE``. Si la semilla pudiera
        resucitar keywords, cada despliegue desharía las decisiones del equipo.
        """
        filas = [
            (tecnologia, keyword)
            for tecnologia, keywords in diccionario.items()
            for keyword in keywords
        ]
        if not filas:
            return 0
        ahora = now_utc_iso()
        with connect() as c:
            antes = c.execute("SELECT COUNT(*) FROM tecnologias_keywords").fetchone()
            if int((antes or [0])[0]):
                # Ya sembrada: no se reinsertan 400 filas en cada arranque sólo
                # para que `ON CONFLICT` las descarte una a una.
                return 0
            c.executemany(
                "INSERT INTO tecnologias_keywords "
                "(tecnologia, keyword, activa, created_at, updated_at) "
                "VALUES (%s, %s, TRUE, %s, %s) ON CONFLICT DO NOTHING",
                [(t, k, ahora, ahora) for t, k in filas],
            )
            despues = c.execute("SELECT COUNT(*) FROM tecnologias_keywords").fetchone()
        return int((despues or [0])[0]) - int((antes or [0])[0])

    def upsert(
        self,
        *,
        tecnologia: str,
        keyword: str,
        activa: bool,
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Añade una keyword o cambia su estado. Devuelve la fila resultante."""
        limpia = " ".join((keyword or "").split()).lower()
        if not limpia or not tecnologia.strip():
            return None
        ahora = now_utc_iso()
        with connect() as c:
            c.execute(
                "INSERT INTO tecnologias_keywords "
                "(tecnologia, keyword, activa, created_by_user_id, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tecnologia, lower(keyword)) "
                "DO UPDATE SET activa = EXCLUDED.activa, updated_at = EXCLUDED.updated_at",
                (tecnologia.strip(), limpia, activa, user_id, ahora, ahora),
            )
            filas = rows_to_dicts(
                c.execute(
                    "SELECT id, tecnologia, keyword, activa, created_at, updated_at "
                    "FROM tecnologias_keywords "
                    "WHERE tecnologia = %s AND lower(keyword) = %s",
                    (tecnologia.strip(), limpia),
                )
            )
        return filas[0] if filas else None

    def impacto(self, keyword: str, *, dias: int = 90) -> dict[str, Any]:
        """Cuántos expedientes recientes traería esta keyword (C5.6).

        Es la pregunta que hay que poder responder **antes** de aplicar un
        cambio: «esta keyword añadiría N expedientes de los últimos 90 días».
        Sin ella, ampliar el diccionario es una apuesta — y la que sale mal
        (una keyword demasiado genérica) mete miles de filas de ruido en el
        corpus y no se nota hasta que alguien mira una gráfica rara.

        Cuenta por separado los que **ya** tienen tecnología: esos no son
        ganancia, sólo confirman que la keyword casa con lo que ya se detecta.
        """
        limpia = " ".join((keyword or "").split()).lower()
        if not limpia:
            return {"keyword": keyword, "dias": dias, "nuevos": 0, "ya_etiquetados": 0}
        patron = f"%{limpia}%"
        with connect_read() as c:
            fila = c.execute(
                "SELECT "
                "COUNT(*) FILTER (WHERE tecnologia IS NULL OR tecnologia = '') AS nuevos, "
                "COUNT(*) FILTER (WHERE tecnologia IS NOT NULL AND tecnologia <> '') "
                "  AS ya_etiquetados "
                "FROM licitaciones "
                "WHERE fecha_publicacion >= to_char(NOW() - make_interval(days => %s), "
                "                                   'YYYY-MM-DD') "
                "  AND (lower(titulo) LIKE %s OR lower(COALESCE(descripcion, '')) LIKE %s)",
                (int(dias), patron, patron),
            ).fetchone()
        return {
            "keyword": limpia,
            "dias": int(dias),
            "nuevos": int((fila or [0, 0])[0] or 0),
            "ya_etiquetados": int((fila or [0, 0])[1] or 0),
        }
