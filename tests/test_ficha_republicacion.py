"""El pliego de una republicación confirmada es el de su canónica.

Caso real (oportunidad 14, 2026-09-30): `ted:657574-2026` es el reenvío al DOUE
del expediente PLACSP `2549/2026` —mismo `idEvl`, duplicado `confirmed`—. TED no
trae adjuntos, así que la ficha, sus citas y el guion de la oportunidad abierta
sobre el anuncio TED se quedaban sin documentos, con los cuatro pliegos de la
canónica ya extraídos.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from db.database import DocumentoReferencia, connect
from db.repositories.dedupe import canonical_for
from db.repositories.documentos import DocumentosRepository
from services.dedupe import expediente_del_pliego
from services.rag.fact_sheet import (
    extract_fact_sheet_on_demand,
    get_fact_sheet,
    run_background_extraction,
)
from services.rag.paginas import get_pagina

TED = "ted:657574-2026"
PLACSP = "2549/2026"
TEXTO = "El criterio precio tendrá una ponderación del 60 por ciento."
CITA = "criterio precio tendrá una ponderación del 60 por ciento"


def _licitacion(id_externo: str, fuente: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (%s, 'Licencias SAP S/4HANA', %s, CURRENT_TIMESTAMP)",
            (id_externo, fuente),
        )


def _duplicado(licitacion_id: str, canonical_id: str, *, status: str = "confirmed") -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones_duplicados "
            "(licitacion_id, canonical_id, confianza, status, clave_match) "
            "VALUES (%s, %s, %s, %s, 'idEvl:test')",
            (licitacion_id, canonical_id, 1.0 if status == "confirmed" else 0.8, status),
        )


def _pliego_extraido(licitacion_id: str) -> int:
    repo = DocumentosRepository()
    repo.upsert_meta(
        licitacion_id,
        [
            DocumentoReferencia(
                tipo="legal", uri="https://example.test/pcap.pdf", filename="PCAP.pdf"
            )
        ],
    )
    documento_id = int(repo.list_by_licitacion(licitacion_id)[0]["id"])
    repo.mark_extracted(documento_id, texto=TEXTO, sha256="abc", pages=[TEXTO])
    return documento_id


def _respuesta_llm(documento_id: int) -> str:
    return json.dumps(
        {
            "award_criteria": [
                {
                    "name": "Precio",
                    "description": "Criterio económico",
                    "weight_pct": 60,
                    "criterion_type": "price",
                    "confidence": 0.95,
                    "evidence": [{"documento_id": documento_id, "page_number": 1, "quote": CITA}],
                }
            ]
        }
    )


def _par_ted_placsp(*, status: str = "confirmed") -> int:
    _licitacion(PLACSP, "placsp")
    _licitacion(TED, "ted")
    _duplicado(TED, PLACSP, status=status)
    return _pliego_extraido(PLACSP)


class TestResolucion:
    def test_una_republicacion_confirmada_usa_los_pliegos_de_su_canonica(self, tmp_db):
        _par_ted_placsp()
        assert expediente_del_pliego(TED) == PLACSP

    def test_la_canonica_y_cualquier_otra_licitacion_son_su_propio_pliego(self, tmp_db):
        _par_ted_placsp()
        assert expediente_del_pliego(PLACSP) == PLACSP
        assert expediente_del_pliego("SIN-DUPLICADO") == "SIN-DUPLICADO"

    def test_un_par_pending_no_sustituye_el_pliego(self, tmp_db):
        """Puede ser otro contrato: enseñar sus requisitos sería peor que nada."""
        _par_ted_placsp(status="pending")
        assert expediente_del_pliego(TED) == TED
        # El aviso del Detalle sigue viendo el par, que es lo que ya hacía.
        assert canonical_for(TED) == PLACSP
        assert canonical_for(TED, solo_confirmadas=True) is None


class TestFicha:
    def test_extraer_desde_el_anuncio_ted_extrae_la_de_la_canonica(self, tmp_db):
        documento_id = _par_ted_placsp()
        with patch(
            "services.rag.fact_sheet.stream_llm_response",
            return_value=iter([_respuesta_llm(documento_id)]),
        ):
            record = extract_fact_sheet_on_demand(TED, model="gpt-4o-mini")

        assert record.licitacion_id == PLACSP
        assert record.status == "extracted"
        leida = get_fact_sheet(TED)
        assert leida is not None
        assert leida.licitacion_id == PLACSP
        assert leida.facts is not None
        assert [c.name for c in leida.facts.award_criteria] == ["Precio"]

    def test_el_fallo_sin_paginas_queda_donde_se_va_a_leer(self, tmp_db):
        """El `failed` en la fila del anuncio TED no lo leería nadie: el polling
        vería «Aún no hay ficha» para siempre en vez del motivo."""
        _licitacion(PLACSP, "placsp")
        _licitacion(TED, "ted")
        _duplicado(TED, PLACSP)

        run_background_extraction(TED, model="gpt-4o-mini")  # nunca lanza

        ficha = get_fact_sheet(TED)
        assert ficha is not None
        assert ficha.licitacion_id == PLACSP
        assert ficha.status == "failed"
        assert ficha.error_detail


class TestCitasYDocumentos:
    def test_la_pagina_citada_se_sirve_desde_el_anuncio_ted(self, tmp_db):
        documento_id = _par_ted_placsp()
        pagina = get_pagina(TED, documento_id, 1)
        assert pagina is not None
        assert CITA in pagina.texto

    def test_documentos_del_anuncio_ted_son_los_de_su_canonica(self, client, auth):
        _par_ted_placsp()
        r = client.get(f"/api/v1/licitaciones/{TED}/documentos", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert data["id_externo"] == TED
        assert [d["filename"] for d in data["items"]] == ["PCAP.pdf"]
