"""F6.2 — «este dato está mal»: la entrada que el usuario no tenía.

El producto vende confianza en el dato y sólo aceptaba una corrección: la
tecnología, desde el panel de active learning. Un usuario que ve la CCAA
cambiada, un expediente duplicado o un adjudicatario que no es, no tiene dónde
decirlo — y quien no puede corregir, deja de confiar y de mirar.

Dónde aterrizan los reportes
----------------------------
En ``ml_feedback``, con ``source = 'reporte:<tipo>'``. No es un atajo: es la
cola de revisión que ya existe, con su expediente, su nota, su autor y su
fecha, y **todos** sus consumidores de ML filtran por ``source = 'human'``
(``scraper/ml_training.py``, ``scheduler/concept_drift.py``,
``db/model_registry.py``, ``db/repositories/licitaciones.py``). Un reporte por
tanto no puede convertirse en una etiqueta de entrenamiento por accidente,
que es el único riesgo real de reutilizar esta tabla.

Los tipos que tienen cola propia aguas abajo —``duplicado`` va a la revisión
de dedupe, ``adjudicatario`` a ``empresa_review_queue``— se distinguen por su
``source`` y se recogen desde ahí. La alternativa era una tabla nueva por
tipo, que es tres colas más que mantener para el mismo trabajo.

``relevante`` se guarda a 0 porque la columna es NOT NULL y porque es lo que
un reporte significa: una señal negativa sobre esta fila. Ningún consumidor la
lee para estos registros.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

from db.repositories.feedback import FeedbackRepository
from observability.logging import get_logger

log = get_logger(__name__)

_repo = FeedbackRepository()

#: Lista cerrada. Abierta no se podría agregar —el mismo argumento que D37 usa
#: para los motivos de pérdida— y la vista de Calidad quedaría sin cortes.
TipoReporte = Literal[
    "tecnologia",
    "ccaa",
    "duplicado",
    "importe",
    "adjudicatario",
    "otro",
]

TIPOS_REPORTE: Final[tuple[str, ...]] = get_args(TipoReporte)

#: Prefijo de ``ml_feedback.source`` para estas filas. Se comparte con la
#: consulta de la vista de Calidad, que agrupa por él.
PREFIJO_SOURCE: Final = "reporte:"

#: A qué cola de revisión pertenece cada tipo. Es documentación ejecutable: el
#: test comprueba que todo tipo tiene destino, para que añadir uno nuevo
#: obligue a decidir quién lo revisa en vez de dejarlo cayendo en el limbo.
COLA_POR_TIPO: Final[dict[str, str]] = {
    "tecnologia": "ml_feedback",
    "ccaa": "ml_feedback",
    "importe": "ml_feedback",
    "otro": "ml_feedback",
    "duplicado": "dedupe",
    "adjudicatario": "empresas",
}


def source_de(tipo: str) -> str:
    """El ``source`` con el que se guarda un reporte de este tipo."""
    return f"{PREFIJO_SOURCE}{tipo}"


def registrar_reporte(
    *,
    id_externo: str,
    tipo: TipoReporte,
    comentario: str | None,
    user_id: int | None,
) -> str:
    """Guarda el reporte y devuelve su marca de tiempo.

    El comentario es opcional y va tal cual a ``nota``: es texto del usuario
    sobre un expediente concreto, así que **no** viaja a la telemetría (sólo
    el ``tipo``, que es categórico) y no se usa para nada automático.
    """
    creado = _repo.insert(
        expediente=id_externo,
        relevante=False,
        nota=(comentario or "").strip()[:2000],
        source=source_de(tipo),
        user_id=user_id,
    )
    log.info("dato_reportado", tipo=tipo, cola=COLA_POR_TIPO[tipo])
    return creado
