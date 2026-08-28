"""Coberturas NO medidas de Calidad de Datos: se abstienen, no publican 0,0 %.

Fichero aparte de ``test_analytics_quality.py`` (completitud, DLQ, formato ISO)
porque lo que fija es una regla de contrato, no una métrica: ``cobertura_nif`` y
``cobertura_modulo_sap`` no salen de ninguna columna de ``licitaciones``, así
que el único valor honesto es ``None``.

El servicio devolvía el literal ``0.0`` —herencia del guard
``if col in df.columns`` del camino pandas— y la guarda del frontend
(``!= null``) lo daba por bueno: la pantalla cuya única función es acreditar la
calidad del dato afirmaba que esas dos coberturas eran cero. Con ``None`` la
tarjeta se abstiene («—»), que es lo que corresponde a algo que nadie mide.
"""

from __future__ import annotations

import pytest

from services.analytics.quality import get_quality

pytestmark = pytest.mark.usefixtures("tmp_db")


def _seed_una_licitacion() -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo="Q1",
                titulo="Servicio de mantenimiento",
                fecha_publicacion="2026-01-15",
                importe=10_000.0,
                cpv="72000000",
                estado="PUB",
            )
        ]
    )


def test_coberturas_sin_medir_son_none_con_datos():
    _seed_una_licitacion()

    result = get_quality()

    assert result.total_records == 1
    # NO 0.0: un cero se lee como una medida, y no hay medida.
    assert result.cobertura_nif is None
    assert result.cobertura_modulo_sap is None
    # El resto de la pantalla sí mide, y no se ve afectado por la abstención.
    assert result.pct_cpv == 100.0


def test_coberturas_sin_medir_son_none_con_dataset_vacio():
    result = get_quality()

    assert result.total_records == 0
    assert result.cobertura_nif is None
    assert result.cobertura_modulo_sap is None
