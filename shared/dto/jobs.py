"""Cola de trabajo y worker: estado y resultado de un job encolado."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from shared.dto.primitivas import PgDateTime

# ── ANCLA S5 — cola de trabajo y worker ────────────────────────────────────
#
# Los dos modelos de abajo cumplen el criterio de compartición del docstring:
# los publican tres rutas de ficheros distintos —``GET /jobs/{id}``
# (``api/routes/jobs.py``), el 202 de ``…/ficha-pliego/extract-async`` y el de
# ``…/embeddings-async`` (``api/routes/licitaciones.py``) y el 202 de
# ``GET /exports/download`` (``api/routes/exports.py``)—, así que dejarlos en
# una de ellas obligaría a las otras dos a importarla.


class JobResultado(BaseModel):
    """Lo que un job terminado publica, con los campos de cada tipo.

    Un solo modelo con todos los campos opcionales en vez de una unión por
    tipo, y es una decisión, no pereza: ``dict[str, Any]`` habría dado
    ``{ [key: string]: unknown }`` en el cliente (invariante §3.5), y una unión
    discriminada obligaría al frontend a estrechar por tipo para leer un
    ``descarga`` que solo necesita cuando existe. Cada campo dice qué tipo lo
    rellena.
    """

    #: ``export_pdf``: filas que entraron en el documento.
    filas: int | None = None
    #: ``export_pdf``: tamaño del PDF maquetado.
    bytes: int | None = None
    #: ``export_pdf``: ruta con la que descargarlo mientras siga en caché.
    descarga: str | None = None
    #: ``ficha_pliego`` y ``embeddings_expediente``: expediente afectado.
    licitacion_id: str | None = None
    #: ``ficha_pliego``: estado en que quedó la fila de ``tender_fact_sheets``.
    estado_ficha: str | None = None
    #: ``ficha_pliego``: hechos y citas validadas de la ficha.
    campos: int | None = None
    citas: int | None = None
    #: ``embeddings_expediente``: documentos procesados y chunks escritos.
    documentos: int | None = None
    chunks: int | None = None


class JobEstadoDTO(BaseModel):
    """Estado de un trabajo encolado (``GET /jobs/{id}``).

    ``intentos`` se publica porque es lo que distingue «está tardando» de «va
    por el segundo reintento»: sin ese número, un job que reaparece en
    ``pending`` tras fallar parece uno recién encolado.
    """

    id: int
    tipo: str
    estado: Literal["pending", "running", "done", "failed"]
    intentos: int
    #: Cuándo vuelve a ser reclamable. Con el backoff, es la fecha en la que el
    #: cliente puede dejar de sondear hasta el siguiente intento.
    run_after: PgDateTime
    created_at: PgDateTime
    updated_at: PgDateTime
    resultado: JobResultado | None = None
    error_detail: str | None = None
