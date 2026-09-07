"""Voto de calidad sobre las respuestas del asistente (C5.4).

Los pulgares del chat existían desde hacía meses y el voto era **solo un evento
de telemetría**: no llegaba a ninguna tabla y no había forma de responder «¿el
asistente responde peor este mes que el pasado?». Se le pedía al usuario que
evaluase y su evaluación se tiraba.

**La fila lleva la forma del turno, no su contenido**: hash con sal de la
pregunta, modo, modelo, voto y un motivo de lista cerrada. El texto en claro
solo con opt-in explícito, en columna aparte, para que una consulta que no lo
pida no lo lea por accidente.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

#: Motivos que la UI ofrece. Lista cerrada a propósito: un campo libre aquí
#: sería una vía por la que el usuario pega la pregunta —o datos de su oferta—
#: en una tabla que declara no guardar texto.
MOTIVOS = frozenset({"incompleta", "incorrecta", "sin_fuentes", "desactualizada", "otro"})

MODOS = frozenset({"pregunta", "resumen", "ficha"})

VOTOS = frozenset({"si", "no"})

#: Tope de la pregunta guardada con opt-in. Una pregunta de chat no llega a
#: tanto; lo que sí llega es un pegado accidental de un pliego entero.
MAX_PREGUNTA = 1000


def hash_pregunta(pregunta: str) -> str:
    """HMAC de la pregunta normalizada, con la clave del servidor como sal.

    Sin sal, un hash de un texto corto y adivinable —«¿cuál es el plazo?»— se
    revierte con un diccionario en minutos, y la columna «sin PII» tendría
    exactamente el contenido que dice no tener.

    Si no hay ``SIGNING_KEY`` (entorno de desarrollo) cae a un SHA-256 sin sal:
    en dev no hay preguntas reales que proteger, y fallar aquí dejaría el voto
    sin registrar por una variable de producción.
    """
    from config.settings import settings

    normalizada = " ".join((pregunta or "").split()).casefold()
    clave = getattr(settings, "SIGNING_KEY", "") or ""
    if not clave:
        return hashlib.sha256(normalizada.encode("utf-8")).hexdigest()[:32]
    return hmac.new(clave.encode("utf-8"), normalizada.encode("utf-8"), hashlib.sha256).hexdigest()[
        :32
    ]


def registrar(
    *,
    pregunta: str,
    modo: str,
    voto: str,
    modelo: str | None = None,
    licitacion_id: str | None = None,
    motivo: str | None = None,
    texto_opt_in: bool = False,
    user_id: int | None = None,
) -> int | None:
    """Guarda un voto. Devuelve el id de la fila, o ``None`` si no se pudo.

    No lanza: un fallo guardando el voto no puede romper la pantalla de quien lo
    emitió — el usuario está haciéndonos un favor, no una transacción.
    """
    if voto not in VOTOS or modo not in MODOS:
        log.warning("asistente_feedback_valores_invalidos", modo=modo, voto=voto)
        return None
    if motivo is not None and motivo not in MOTIVOS:
        motivo = "otro"

    fila = (
        hash_pregunta(pregunta),
        modo,
        modelo,
        licitacion_id,
        voto,
        motivo,
        (pregunta or "")[:MAX_PREGUNTA] if texto_opt_in else None,
        user_id,
        now_utc_iso(),
    )
    try:
        with connect() as c:
            cur = c.execute(
                "INSERT INTO asistente_feedback "
                "(pregunta_hash, modo, modelo, licitacion_id, voto, motivo, pregunta_texto, "
                " user_id, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                fila,
            )
            devuelto = cur.fetchone()
            return int(devuelto[0]) if devuelto else None
    except Exception:
        log.warning("asistente_feedback_insert_failed", exc_info=True)
        return None


def resumen(dias: int = 30) -> dict[str, Any]:
    """Contadores por modo para el panel de `/ops` → Active learning.

    El ratio de útiles es la métrica; el total es su población. Publicar el
    ratio sin el total dejaría un «40 % de satisfacción» que puede venir de dos
    votos.
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT modo, voto, COUNT(*) AS n FROM asistente_feedback "
            "WHERE created_at >= (CURRENT_DATE - CAST(%s AS INTEGER))::text "
            "GROUP BY modo, voto",
            (int(dias),),
        )
        filas = rows_to_dicts(cur)

    por_modo: dict[str, dict[str, int]] = {}
    for fila in filas:
        entrada = por_modo.setdefault(str(fila["modo"]), {"si": 0, "no": 0})
        entrada[str(fila["voto"])] = int(fila["n"])
    return {
        "dias": int(dias),
        "modos": [
            {
                "modo": modo,
                "utiles": conteos["si"],
                "no_utiles": conteos["no"],
                "total": conteos["si"] + conteos["no"],
            }
            for modo, conteos in sorted(por_modo.items())
        ],
    }


def peores_preguntas(limit: int = 20, dias: int = 30) -> list[dict[str, Any]]:
    """Preguntas con más votos negativos, agrupadas por hash.

    Es el insumo de active learning que el voto existía para producir: sin
    agrupar, «una respuesta mala» y «la misma respuesta mala doscientas veces»
    se leen igual. ``ejemplo`` solo trae texto de las filas con opt-in.
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT pregunta_hash, modo, "
            "       SUM(CASE WHEN voto = 'no' THEN 1 ELSE 0 END) AS negativos, "
            "       COUNT(*) AS total, "
            "       MAX(pregunta_texto) AS ejemplo, "
            "       MAX(created_at) AS ultima_vez "
            "FROM asistente_feedback "
            "WHERE created_at >= (CURRENT_DATE - CAST(%s AS INTEGER))::text "
            "GROUP BY pregunta_hash, modo "
            "HAVING SUM(CASE WHEN voto = 'no' THEN 1 ELSE 0 END) > 0 "
            "ORDER BY negativos DESC, ultima_vez DESC LIMIT %s",
            (int(dias), max(1, min(int(limit), 200))),
        )
        return rows_to_dicts(cur)


def preguntas_con_opt_in(limit: int = 500) -> list[dict[str, Any]]:
    """Preguntas cuyo autor autorizó guardar el texto.

    Es lo único que ``eval_rag_generation`` puede reutilizar: el resto de la
    tabla son hashes, y un hash no se le puede preguntar a un modelo.
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT pregunta_texto, modo, licitacion_id, voto, motivo, created_at "
            "FROM asistente_feedback WHERE pregunta_texto IS NOT NULL "
            "ORDER BY created_at DESC LIMIT %s",
            (max(1, min(int(limit), 5000)),),
        )
        return rows_to_dicts(cur)


def borrar_de_usuario(user_id: int) -> int:
    """Borra los votos de un usuario (export/borrado RGPD).

    Borra la **fila entera** y no solo el `user_id`: el voto sin autor sigue
    siendo válido como métrica, pero `pregunta_texto` solo está ahí porque esa
    persona lo autorizó, y esa autorización se va con ella.
    """
    with connect() as c:
        cur = c.execute("DELETE FROM asistente_feedback WHERE user_id = %s", (user_id,))
        return int(getattr(cur, "rowcount", 0) or 0)
