"""TED no entra en el target de baja: no publica presupuesto base.

Su ``importe`` es el valor estimado (BT-27) o, sin él, el propio adjudicado
(BT-161), así que la baja contra lo adjudicado sale inflada o 0 por
construcción. Medido el 2026-11-07: el 83 % de los pares TED del dataset valía
exactamente 0. El HHI sí los usa: no compara contra presupuesto.
"""

from __future__ import annotations

import pytest

from db.repositories.ml_dataset import MlDatasetRepository


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _seed(c, lic_id: str, fuente: str) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
        " importe, tipo_contrato, fuente, fecha_publicacion, fecha_extraccion) "
        "VALUES (%s, 'Lic', 'Organo A', '72000000', 'Madrid', 100000, 'Servicios', "
        " %s, '2025-06-01', CURRENT_TIMESTAMP)",
        (lic_id, fuente),
    )
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
        " fecha_adjudicacion, n_ofertas_recibidas, fecha_extraccion) "
        "VALUES (%s, 'E1', 100000, '2025-09-01', 1, CURRENT_TIMESTAMP)",
        (lic_id,),
    )


def test_ted_sale_del_target_de_baja_pero_no_del_hhi(db):
    with db.connect() as c:
        _seed(c, "PLACSP1", "placsp")
        _seed(c, "ted:1", "ted")

    repo = MlDatasetRepository()
    assert [f["id_externo"] for f in repo.pares_baja_agregada()] == ["PLACSP1"]
    assert [f["id_externo"] for f in repo.pares_baja_por_lote()] == ["PLACSP1"]
    assert sorted(f["licitacion_id"] for f in repo.adjudicaciones_por_empresa()) == [
        "PLACSP1",
        "ted:1",
    ]
