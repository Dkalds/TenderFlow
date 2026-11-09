"""Lecturas de un acuerdo marco o un SDA como expediente (ficha de la licitación).

Todo el SQL vive aquí (ADR-022). Qué cuenta como admitido y si la organización
que mira está entre ellos lo decide ``services/marcos.py``.

Un marco es una fila de ``licitaciones`` con ``sistema_contratacion`` (v178) en
``marco`` o ``sda``; sus admitidos son sus adjudicatarios. Las dos lecturas van
por la clave primaria o por ``idx_adj_licitacion``.
"""

from __future__ import annotations

from typing import TypedDict

from db.database import connect_read
from db.repositories.base import rows_to_dicts, typed_rows
from db.repositories.renovaciones import dias_restantes_sql
from db.sql_fragments import fecha_fin_origen_sql, fecha_fin_sql

__all__ = ["FilaAdmitido", "FilaExpedienteMarco", "admitidos", "expediente"]


class FilaExpedienteMarco(TypedDict):
    """El expediente, con su sistema de contratación y su fecha de fin efectiva."""

    id_externo: str
    sistema_contratacion: str | None
    #: ``YYYY-MM-DD``, publicada o calculada con la duración; ``None`` sin dato.
    fecha_fin: str | None
    #: De dónde sale ``fecha_fin``: ``db.sql_fragments.ORIGENES_FECHA_FIN``.
    fecha_fin_origen: str
    dias_restantes: int | None


class FilaAdmitido(TypedDict):
    """Un adjudicatario del marco en uno de sus lotes, tal como lo publicó la fuente."""

    nombre: str
    nif: str | None
    empresa_id: int | None
    #: ``None`` si la adjudicación es del expediente completo.
    lote_numero: str | None


def expediente(id_externo: str) -> FilaExpedienteMarco | None:
    """El expediente con su vigencia, o ``None`` si no existe.

    La fecha de fin es la de Renovaciones (:func:`db.sql_fragments.fecha_fin_sql`),
    para que la ficha y el listado de Mercado digan el mismo día. Aquella se
    calcula por adjudicación; un marco tiene una por admitido y lote, así que
    aquí cuenta la primera: es la fila que Renovaciones enseña antes.
    """
    fecha_fin = fecha_fin_sql()
    sql = f"""
        SELECT l.id_externo,
               l.sistema_contratacion,
               {fecha_fin} AS fecha_fin,
               {fecha_fin_origen_sql()} AS fecha_fin_origen,
               {dias_restantes_sql(fecha_fin)} AS dias_restantes
        FROM licitaciones l
        LEFT JOIN LATERAL (
            SELECT min(fecha_adjudicacion) AS fecha_adjudicacion
            FROM adjudicaciones WHERE licitacion_id = l.id_externo
        ) a ON TRUE
        WHERE l.id_externo = %s
    """
    with connect_read() as c:
        filas = typed_rows(FilaExpedienteMarco, rows_to_dicts(c.execute(sql, (id_externo,))))
    return filas[0] if filas else None


def admitidos(id_externo: str) -> list[FilaAdmitido]:
    """Los adjudicatarios del expediente, una fila por adjudicatario y lote."""
    with connect_read() as c:
        cur = c.execute(
            "SELECT a.nombre, a.nif, a.empresa_id, lo.numero AS lote_numero "
            "FROM adjudicaciones a "
            "LEFT JOIN lotes lo ON lo.id = a.lote_id "
            "WHERE a.licitacion_id = %s "
            "ORDER BY a.nombre, lo.numero NULLS FIRST, a.id",
            (id_externo,),
        )
        return typed_rows(FilaAdmitido, rows_to_dicts(cur))
