"""Votos sobre las respuestas del asistente (C5.4).

El bucle de active learning que ya existía mide el **clasificador** —si un
expediente es relevante—, no el asistente. De la calidad de ``/ask`` no había ni
un número: ni cuántas respuestas se dan por buenas, ni qué preguntas fallan
siempre, ni si un modelo se comporta peor que otro.

El esquema lo crea ``v120``, y su docstring explica por qué la fila no lleva ni
texto libre ni usuario.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

#: Vocabulario cerrado, espejo de los `CHECK` de `v120`.
VOTOS = ("up", "down")
MOTIVOS = ("incorrecta", "incompleta", "sin_fuentes", "lenta", "otro")

_ESPACIOS_RE = re.compile(r"\s+")


def hash_pregunta(pregunta: str) -> str:
    """Huella de la pregunta, estable frente al formato y no reversible.

    Normaliza espacios y mayúsculas para que «¿Cuál es el plazo?» y «cual es
    el  plazo» agreguen juntas: si no, la señal «esta pregunta falla siempre»
    se reparte entre veinte huellas y no se ve ninguna.
    """
    normalizada = _ESPACIOS_RE.sub(" ", pregunta.strip().lower())
    return hashlib.sha256(normalizada.encode("utf-8")).hexdigest()


class AsistenteFeedbackRepository:
    """Acceso a ``asistente_feedback``."""

    def registrar(
        self,
        *,
        pregunta: str,
        modo: str,
        modelo: str,
        voto: str,
        motivo: str | None = None,
        id_externo: str | None = None,
        cached: bool = False,
        compartir_pregunta: bool = False,
    ) -> int | None:
        """Guarda un voto. Devuelve el id, o ``None`` si el voto no es válido.

        ``compartir_pregunta`` es el **único** camino por el que el texto llega
        a la tabla, y por eso el valor por defecto es no compartir: un opt-in
        que hay que marcar es lo que separa «cedí mi pregunta» de «no me di
        cuenta».
        """
        if voto not in VOTOS:
            return None
        if motivo is not None and motivo not in MOTIVOS:
            return None
        with connect() as c:
            fila = c.execute(
                "INSERT INTO asistente_feedback "
                "(pregunta_hash, pregunta_texto, modo, modelo, voto, motivo, "
                " id_externo, cached) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    hash_pregunta(pregunta),
                    pregunta.strip() if compartir_pregunta else None,
                    modo,
                    modelo,
                    voto,
                    motivo,
                    id_externo,
                    cached,
                ),
            ).fetchone()
        return int(fila[0]) if fila else None

    def resumen(self, *, limite: int = 20) -> dict[str, Any]:
        """Lo que el panel de ``/ops`` necesita para decir algo, no para decorar.

        Tres cifras y dos listas: el balance global, el balance por modelo —que
        es lo que permite decidir si el modelo nuevo es mejor— y las preguntas
        que más votos negativos acumulan, que son la cola de trabajo real.
        """
        with connect_read() as c:
            totales = c.execute(
                "SELECT voto, COUNT(*) FROM asistente_feedback GROUP BY voto"
            ).fetchall()
            por_modelo = rows_to_dicts(
                c.execute(
                    "SELECT modelo, "
                    "COUNT(*) FILTER (WHERE voto = 'up') AS positivos, "
                    "COUNT(*) FILTER (WHERE voto = 'down') AS negativos "
                    "FROM asistente_feedback GROUP BY modelo ORDER BY 2 + 3 DESC"
                )
            )
            peores = rows_to_dicts(
                c.execute(
                    "SELECT pregunta_hash, "
                    # `MAX` y no `ANY`: sólo hay texto en las filas con opt-in,
                    # y basta una para poder enseñar de qué pregunta se habla.
                    "MAX(pregunta_texto) AS pregunta_texto, "
                    "MAX(modo) AS modo, "
                    "COUNT(*) FILTER (WHERE voto = 'down') AS negativos, "
                    "COUNT(*) AS total, MAX(created_at) AS ultima_vez "
                    "FROM asistente_feedback GROUP BY pregunta_hash "
                    "HAVING COUNT(*) FILTER (WHERE voto = 'down') > 0 "
                    "ORDER BY 4 DESC, 6 DESC LIMIT %s",
                    (max(1, min(int(limite), 200)),),
                )
            )
        conteo = {str(v): int(n) for v, n in totales}
        positivos, negativos = conteo.get("up", 0), conteo.get("down", 0)
        total = positivos + negativos
        return {
            "positivos": positivos,
            "negativos": negativos,
            "total": total,
            # `None` y no `0.0` cuando no hay votos: un 0 % de satisfacción sin
            # un solo voto es una cifra que asusta y no significa nada.
            "pct_positivos": round(100.0 * positivos / total, 1) if total else None,
            "por_modelo": por_modelo,
            "peores_preguntas": peores,
        }

    def preguntas_compartidas(self, *, limite: int = 200) -> list[dict[str, Any]]:
        """Preguntas cedidas con opt-in, para reutilizarlas en ``eval_rag_generation``.

        Es la razón por la que el opt-in existe: una batería de evaluación
        escrita por quien programa el sistema mide lo que quien programa
        imaginó, no lo que la gente pregunta de verdad.
        """
        with connect_read() as c:
            return rows_to_dicts(
                c.execute(
                    "SELECT DISTINCT ON (pregunta_hash) pregunta_hash, pregunta_texto, "
                    "modo, id_externo "
                    "FROM asistente_feedback WHERE pregunta_texto IS NOT NULL "
                    "ORDER BY pregunta_hash, created_at DESC LIMIT %s",
                    (max(1, min(int(limite), 1000)),),
                )
            )
