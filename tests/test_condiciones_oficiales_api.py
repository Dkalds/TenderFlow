"""``GET /licitaciones/{id}/condiciones-oficiales`` contra Postgres (v149).

La ruta sirve lo que el parser leyó de la publicación oficial, separado de la
ficha LLM del pliego: un expediente con condiciones las devuelve agrupadas por
ámbito; uno sin ellas responde 200 con la lista vacía —«no publicadas» es un
estado, no un error—; uno que no existe, 404. Se usa un id con barra y
espacio, como los de PLACSP, porque la ruta cuelga de ``{id_externo:path}``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from db.upsert import (
    CondicionesCodice,
    CriterioAdjudicacion,
    GarantiaExigida,
    Licitacion,
    Lote,
    RequisitoSolvencia,
    replace_lotes,
    upsert_licitaciones_with_history,
)

ID = "PA-S 2026/000149"
URL = f"/api/v1/licitaciones/{quote(ID)}/condiciones-oficiales"


def _sembrar(condiciones: CondicionesCodice | None) -> None:
    upsert_licitaciones_with_history(
        [
            Licitacion(
                id_externo=ID,
                titulo="Soporte SAP S/4HANA",
                url="https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=149",
                condiciones=condiciones,
            )
        ],
        source="placsp",
    )


def test_devuelve_las_condiciones_agrupadas_por_ambito(client: Any, auth: Any) -> None:
    _sembrar(
        CondicionesCodice(
            criterios=[
                CriterioAdjudicacion(
                    orden=1, descripcion="Precio", peso=60.0, peso_pct=60.0, es_precio=True
                ),
                CriterioAdjudicacion(orden=2, descripcion="Memoria", peso=40.0, peso_pct=40.0),
            ],
            garantias=[GarantiaExigida(orden=1, lote_numero="1", tipo_codigo="2", porcentaje=5.0)],
            solvencia=[
                RequisitoSolvencia(
                    orden=1, clase="economica", umbral_importe=300_000.0, moneda="EUR"
                )
            ],
        )
    )
    replace_lotes(ID, [Lote(licitacion_id=ID, numero="1", titulo="Licencias")])

    resp = client.get(URL, headers=auth)

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["licitacion_id"] == ID
    assert cuerpo["fuente"] == "placsp"
    assert cuerpo["url_publicacion"].startswith("https://contrataciondelestado.es/")
    assert cuerpo["actualizado"]
    expediente, lote = cuerpo["ambitos"]
    assert expediente["lote_numero"] is None
    assert [(c["descripcion"], c["peso_pct"], c["es_precio"]) for c in expediente["criterios"]] == [
        ("Precio", 60.0, True),
        ("Memoria", 40.0, False),
    ]
    assert expediente["solvencia"][0]["umbral_importe"] == 300_000.0
    assert (lote["lote_numero"], lote["lote_titulo"]) == ("1", "Licencias")
    assert lote["garantias"][0]["porcentaje"] == 5.0


def test_sin_condiciones_responde_200_con_la_lista_vacia(client: Any, auth: Any) -> None:
    _sembrar(None)

    resp = client.get(URL, headers=auth)

    assert resp.status_code == 200
    assert resp.json()["ambitos"] == []


def test_un_expediente_que_no_existe_es_404(client: Any, auth: Any) -> None:
    resp = client.get("/api/v1/licitaciones/NO-EXISTE/condiciones-oficiales", headers=auth)

    assert resp.status_code == 404


def test_sin_credenciales_es_401(client: Any) -> None:
    _sembrar(None)

    assert client.get(URL).status_code == 401
