"""Listado de candidatos para el golden de la ficha del pliego.

Es la consulta con la que se eligen los diez pliegos de referencia
(``scripts/capturar_ficha_golden.py --listar``): tiene que ofrecer también los
expedientes con páginas y sin ficha, porque ahí está lo que la ficha omite.
"""

from __future__ import annotations

from db.database import DocumentoReferencia, connect
from db.repositories.documentos import DocumentosRepository
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository


def _licitacion(licitacion_id: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (%s, 'Contrato con pliego', 'placsp', CURRENT_TIMESTAMP)",
            (licitacion_id,),
        )


def _con_pagina(licitacion_id: str) -> None:
    _licitacion(licitacion_id)
    repo = DocumentosRepository()
    repo.upsert_meta(
        licitacion_id,
        [DocumentoReferencia(tipo="legal", uri=f"https://example.test/{licitacion_id}.pdf")],
    )
    doc = repo.list_pendientes()[0]
    texto = "El criterio precio tendrá una ponderación del 60 por ciento."
    repo.mark_extracted(doc["id"], texto=texto, sha256=f"sha-{licitacion_id}", pages=[texto])


def _lote(numero: str) -> dict[str, object]:
    return {"lot_number": numero, "description": f"Lote {numero}", "confidence": 0.9}


def test_lista_solo_licitaciones_con_paginas_y_cuenta_lotes(tmp_db):
    _con_pagina("CAND-A")
    _con_pagina("CAND-B")
    _licitacion("CAND-C")
    repo = TenderFactSheetsRepository()
    repo.upsert(
        licitacion_id="CAND-A",
        status="extracted",
        extraction_version="tender-facts-v6",
        model="modelo-x",
        facts={"lots": [_lote("1"), _lote("2")], "price_formula": []},
        field_count=2,
        evidence_count=0,
    )

    filas = {f["licitacion_id"]: f for f in repo.list_candidatas_golden()}

    assert "CAND-C" not in filas
    con_ficha = filas["CAND-A"]
    assert (con_ficha["lotes"], con_ficha["formulas"]) == (2, 0)
    assert (con_ficha["documentos"], con_ficha["paginas"], con_ficha["paginas_ocr"]) == (1, 1, 0)
    assert (con_ficha["fuente"], con_ficha["status"], con_ficha["field_count"]) == (
        "placsp",
        "extracted",
        2,
    )
    sin_ficha = filas["CAND-B"]
    assert sin_ficha["status"] is None
    assert (sin_ficha["lotes"], sin_ficha["formulas"]) == (0, 0)


def test_una_ficha_fallida_sin_datos_no_rompe_el_listado(tmp_db):
    _con_pagina("CAND-F")
    repo = TenderFactSheetsRepository()
    repo.upsert(
        licitacion_id="CAND-F",
        status="failed",
        extraction_version="tender-facts-v6",
        model="modelo-x",
        facts=None,
        field_count=0,
        evidence_count=0,
        error_detail="respuesta vacía",
    )

    (fila,) = repo.list_candidatas_golden()

    assert (fila["status"], fila["lotes"], fila["formulas"]) == ("failed", 0, 0)
