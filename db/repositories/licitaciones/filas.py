"""Formas de fila (``TypedDict``) de las consultas de ``licitaciones``."""

from __future__ import annotations

from typing import TypedDict

# ── Formas de fila ──────────────────────────────────────────────────────────
# Un ``TypedDict`` por SELECT de columnas fijas: las claves son sus alias y los
# tipos, lo que psycopg devuelve para esas columnas (``db/models.py``): TEXT y
# VARCHAR → ``str``, ``Float``/``double precision`` → ``float``, todo nulable
# salvo ``id_externo``, ``titulo`` y ``fecha_extraccion`` (``NOT NULL``). El
# importe proyectado por el núcleo tipado (``importe_sql``) se castea a
# ``double precision``, así que también es ``float``. ``get_by_id`` (``SELECT *``)
# queda como ``dict[str, Any]``: sus columnas cambian con cada migración.


class LicitacionResumenRow(TypedDict):
    """Una fila de listado: las columnas de ``_SUMMARY_COLS``."""

    id_externo: str
    titulo: str
    organo_contratacion: str | None
    importe: float | None
    estado: str | None
    fecha_publicacion: str | None
    fecha_limite: str | None
    ccaa: str | None
    cpv: str | None
    url: str | None
    tecnologia: str | None
    ml_tecnologias: str | None
    ml_proba_max: float | None
    ml_tech_principal: str | None
    procedimiento: str | None
    tramitacion: str | None


class ProximaRow(TypedDict):
    """Una fila de la bandeja «Próximas» (``_PROXIMAS_COLS``)."""

    id_externo: str
    titulo: str
    organo_contratacion: str | None
    importe: float | None
    estado: str | None
    fecha_publicacion: str | None
    fecha_inicio: str | None
    ccaa: str | None
    cpv: str | None
    url: str | None
    tecnologia: str | None


class TechScoreRow(TypedDict):
    """Una fila de ``licitacion_tecnologia_score`` (todas ``NOT NULL``)."""

    tecnologia: str
    probabilidad: float
    threshold_aplicado: float
    computed_at: str


class CandidatoEtiquetadoRow(TypedDict):
    """Un expediente sin etiquetar para la cola de active learning."""

    id_externo: str
    titulo: str
    descripcion: str | None
    cpv: str | None
    importe: float | None
    organo_contratacion: str | None
    ccaa: str | None
    fecha_publicacion: str | None
    url: str | None
    tecnologia: str | None
    ml_tecnologias: str | None
    ml_proba_max: float | None
    ml_tech_principal: str | None


class ZonaIncertidumbreRow(TypedDict):
    """Un expediente con ``ml_proba`` en la zona de incertidumbre (no nula: la filtra)."""

    id_externo: str
    titulo: str
    descripcion: str | None
    organo_contratacion: str | None
    importe: float | None
    fecha_publicacion: str | None
    cpv: str | None
    ml_proba: float


class DriftRow(TypedDict):
    """Una fila de la ventana de drift."""

    importe: float | None
    cpv: str | None
    ccaa: str | None
    tecnologia: str | None
    estado: str | None


class RecienteRow(TypedDict):
    """Una fila del feed en vivo (SSE)."""

    id_externo: str
    titulo: str
    organo_contratacion: str | None
    importe: float | None
    estado: str | None
    url: str | None
    fecha_publicacion: str | None
    ccaa: str | None
    tecnologia: str | None
    fecha_extraccion: str
    fecha_actualizacion_fuente: str | None


class ExportPdfRow(TypedDict):
    """Una fila de la exportación PDF/CSV."""

    id_externo: str
    titulo: str
    organo_contratacion: str | None
    importe: float | None
    estado: str | None
    fecha_publicacion: str | None
    ccaa: str | None
    cpv: str | None
    url: str | None
    tecnologia: str | None


class HistorialRow(TypedDict):
    """Una fila de ``licitaciones_history``."""

    id: int
    id_externo: str
    captured_at: str
    source: str | None
    snapshot_json: str
    changed_fields: str


class LicitacionLoteRow(TypedDict):
    """Una fila del export por lote: el expediente y, si los tiene, uno de sus lotes.

    Los campos ``lote_*`` vienen del ``LEFT JOIN``: ``NULL`` en un expediente
    sin lotes aunque ``lotes.numero`` sea ``NOT NULL``.
    """

    id_externo: str
    titulo: str
    organo_contratacion: str | None
    importe: float | None
    cpv: str | None
    estado: str | None
    ccaa: str | None
    fecha_publicacion: str | None
    fecha_limite: str | None
    url: str | None
    lote_numero: str | None
    lote_titulo: str | None
    lote_cpv: str | None
    lote_importe: float | None
    lote_fecha_limite: str | None
