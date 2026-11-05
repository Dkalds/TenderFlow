"""``db/repositories/medicion_etiquetas.py``: lo que mide el script de etiquetas.

Contra Postgres (``tmp_db``). Solo entran las licitaciones con alguna etiqueta
y que no son un duplicado confirmado; las que no tienen puntuaciones ni pliego
traen listas vacías, no ``NULL``.
"""

from __future__ import annotations

from tests.escenarios import sembrar_licitacion


def test_solo_las_etiquetadas_y_sin_duplicados_confirmados(tmp_db):
    from db.repositories.medicion_etiquetas import filas_etiquetas_tecnologia

    db_mod, _ = tmp_db
    sembrar_licitacion("CON", "Soporte SAP", tecnologia="SAP")
    sembrar_licitacion("SIN", "Limpieza de oficinas")
    sembrar_licitacion("DUP", "Soporte SAP (copia)", tecnologia="SAP")
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, confianza, "
            "status, detectado_en) VALUES ('DUP', 'CON', 1.0, 'confirmed', %s)",
            ("2026-11-04T00:00:00+00:00",),
        )

    filas = filas_etiquetas_tecnologia()

    assert [f["id_externo"] for f in filas] == ["CON"]
    assert filas[0]["tecnologia"] == "SAP"
    assert filas[0]["ml_scores"] == []
    assert filas[0]["pliego"] == []
