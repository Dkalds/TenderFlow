"""``ensure_documents_ready`` acotado por tipo de documento.

Por defecto solo toca pliegos: las actas de la mesa (``tipo='acta'``) son
referencias que ni la ficha ni el pipeline nocturno descargan (spec de las
puntuaciones del acta, §3.3). La lectura del acta pide su propio tipo con
``tipos={"acta"}``. Sin BD ni red: el repositorio y el fetcher van parchados.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from db.repositories.documentos import TIPO_ACTA
from services.rag.fact_sheet import ensure_documents_ready


def _doc(
    documento_id: int, tipo: str, status: str = "pending", *, sin_publicar: bool = False
) -> dict[str, Any]:
    return {"id": documento_id, "tipo": tipo, "status": status, "sin_publicar": sin_publicar}


def _ejecutar(filas: list[dict[str, Any]], **kwargs: Any) -> tuple[dict[str, int], list[int]]:
    """Corre ``ensure_documents_ready`` y devuelve (conteos, ids que se intentaron)."""
    intentados: list[int] = []

    def _fetch(fila: dict[str, Any]) -> str:
        intentados.append(int(fila["id"]))
        return "extracted"

    repo = MagicMock()
    repo.list_by_licitacion.return_value = filas
    with (
        patch("services.rag.fact_sheet._pdf_extraction_available", return_value=True),
        patch("services.rag.fact_sheet.DocumentosRepository", return_value=repo),
        patch("scraper.document_fetcher.fetch_and_extract", side_effect=_fetch),
    ):
        counts = ensure_documents_ready("EXP-1", **kwargs)
    return counts, intentados


def test_ensure_documents_ready_por_defecto_no_descarga_actas():
    counts, intentados = _ejecutar([_doc(1, "legal"), _doc(2, TIPO_ACTA), _doc(3, "technical")])

    assert intentados == [1, 3]
    assert counts["attempted"] == 2


def test_ensure_documents_ready_por_defecto_ignora_un_expediente_solo_con_actas():
    counts, intentados = _ejecutar([_doc(1, TIPO_ACTA), _doc(2, TIPO_ACTA, "error")])

    assert intentados == []
    assert counts["attempted"] == 0


def test_un_acta_extraida_no_cuenta_como_pliego_extraido():
    """Con el acta ya leída y el pliego en ``error``, el pliego se reintenta.

    Si el acta contara como ``any_extracted``, la ficha se quedaría sin pliego
    y sin reintento: la regla es «los ``error`` se reintentan mientras ningún
    *pliego* haya llegado a ``extracted``».
    """
    _counts, intentados = _ejecutar([_doc(1, "legal", "error"), _doc(2, TIPO_ACTA, "extracted")])

    assert intentados == [1]


def test_ensure_documents_ready_con_tipos_acta_solo_descarga_actas():
    counts, intentados = _ejecutar(
        [_doc(1, "legal"), _doc(2, TIPO_ACTA), _doc(3, TIPO_ACTA)],
        tipos=frozenset({TIPO_ACTA}),
    )

    assert intentados == [2, 3]
    assert counts["attempted"] == 2


def test_ensure_documents_ready_con_tipos_acta_respeta_el_tope():
    actas = [_doc(i, TIPO_ACTA) for i in range(1, 6)]

    counts, intentados = _ejecutar(actas, tipos=frozenset({TIPO_ACTA}), max_documentos=3)

    assert intentados == [1, 2, 3]
    assert counts["attempted"] == 3


def test_ensure_documents_ready_sin_tope_explicito_sigue_en_ocho():
    pliegos = [_doc(i, "additional") for i in range(1, 12)]

    counts, _intentados = _ejecutar(pliegos)

    assert counts["attempted"] == 8
