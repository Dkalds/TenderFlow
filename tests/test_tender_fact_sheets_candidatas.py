"""Listado de candidatos para el golden de la ficha del pliego.

Es la consulta con la que se eligen los diez pliegos de referencia
(``scripts/capturar_ficha_golden.py --listar``). Tiene que enseñar variedad
—todas las fuentes, y tanto las fichas ricas como las pobres, las fallidas y
los expedientes sin ficha—, porque elegir solo entre lo que salió bien mediría
el mejor caso.
"""

from __future__ import annotations

from db.database import DocumentoReferencia, connect
from db.repositories.documentos import DocumentosRepository
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository


def _licitacion(licitacion_id: str, fuente: str = "placsp") -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (%s, 'Contrato con pliego', %s, CURRENT_TIMESTAMP)",
            (licitacion_id, fuente),
        )


def _con_pagina(licitacion_id: str, fuente: str = "placsp") -> None:
    _licitacion(licitacion_id, fuente)
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


def _ficha(licitacion_id: str, *, hechos: int, status: str = "extracted", lotes: int = 0) -> None:
    TenderFactSheetsRepository().upsert(
        licitacion_id=licitacion_id,
        status=status,
        extraction_version="tender-facts-v6",
        model="modelo-x",
        facts=(
            None
            if status == "failed"
            else {"lots": [_lote(str(n)) for n in range(1, lotes + 1)], "price_formula": []}
        ),
        field_count=hechos,
        evidence_count=0,
    )


def test_lista_solo_licitaciones_con_paginas_y_cuenta_lotes(tmp_db):
    _con_pagina("CAND-A")
    _con_pagina("CAND-B")
    _licitacion("CAND-C")
    _ficha("CAND-A", hechos=2, lotes=2)

    filas = {f["licitacion_id"]: f for f in TenderFactSheetsRepository().list_candidatas_golden()}

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


def test_cada_expediente_cae_en_su_grupo(tmp_db):
    for licitacion_id in ("G-RICA", "G-POBRE", "G-FALLIDA", "G-SIN"):
        _con_pagina(licitacion_id)
    _ficha("G-RICA", hechos=12)
    _ficha("G-POBRE", hechos=1)
    _ficha("G-FALLIDA", hechos=0, status="failed")

    grupos = {
        f["licitacion_id"]: f["grupo"]
        for f in TenderFactSheetsRepository().list_candidatas_golden()
    }

    assert grupos == {
        "G-RICA": "rica",
        "G-POBRE": "pobre",
        "G-FALLIDA": "fallida",
        "G-SIN": "sin_ficha",
    }


def test_el_tope_es_por_fuente_y_grupo_y_dice_cuantas_hay_en_total(tmp_db):
    # Con un tope global ordenado por fuente, la primera fuente llenaba la
    # lista y las demás —y las fichas ricas— no llegaban a verse.
    for n in range(3):
        _con_pagina(f"PLACSP-SIN-{n}", "placsp")
    _con_pagina("PLACSP-RICA", "placsp")
    _ficha("PLACSP-RICA", hechos=20)
    _con_pagina("PSCP-SIN", "pscp")

    filas = TenderFactSheetsRepository().list_candidatas_golden(por_grupo=2)

    por_grupo = {(f["fuente"], f["grupo"]): [] for f in filas}
    for fila in filas:
        por_grupo[(fila["fuente"], fila["grupo"])].append(fila)
    assert {clave: len(valor) for clave, valor in por_grupo.items()} == {
        ("placsp", "sin_ficha"): 2,
        ("placsp", "rica"): 1,
        ("pscp", "sin_ficha"): 1,
    }
    assert {f["total_grupo"] for f in por_grupo[("placsp", "sin_ficha")]} == {3}
    assert por_grupo[("pscp", "sin_ficha")][0]["total_grupo"] == 1


def test_se_puede_pedir_una_sola_fuente(tmp_db):
    _con_pagina("PLACSP-1", "placsp")
    _con_pagina("PSCP-1", "pscp")

    filas = TenderFactSheetsRepository().list_candidatas_golden(fuente="pscp")

    assert [f["licitacion_id"] for f in filas] == ["PSCP-1"]


def test_las_fichas_ricas_salen_de_mas_a_menos_hechos(tmp_db):
    for licitacion_id, hechos in (("R-10", 10), ("R-30", 30), ("R-20", 20)):
        _con_pagina(licitacion_id)
        _ficha(licitacion_id, hechos=hechos)

    filas = TenderFactSheetsRepository().list_candidatas_golden(por_grupo=2)

    assert [f["licitacion_id"] for f in filas] == ["R-30", "R-20"]


def test_una_ficha_fallida_sin_datos_no_rompe_el_listado(tmp_db):
    _con_pagina("CAND-F")
    _ficha("CAND-F", hechos=0, status="failed")

    (fila,) = TenderFactSheetsRepository().list_candidatas_golden()

    assert (fila["status"], fila["lotes"], fila["formulas"]) == ("failed", 0, 0)
