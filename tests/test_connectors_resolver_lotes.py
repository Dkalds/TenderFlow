"""``resolver_lotes_adjudicaciones``: cada adjudicación a su lote, y cuántas no.

Sin base de datos: el mapeo ``{numero: lote_id}`` es lo que devolvería
``replace_lotes_batch``. El recuento ``sin_lote`` es la señal que delata un
formato de lote que el parser no lee —hasta 2026-10 era el 100 % de las
adjudicaciones de expedientes multilote, y nadie lo vio—.
"""

from __future__ import annotations

from db.upsert import Adjudicacion
from scraper.connectors.base import resolver_lotes_adjudicaciones


def _adj(licitacion_id: str, lote: str | None) -> Adjudicacion:
    return Adjudicacion(licitacion_id=licitacion_id, nombre="Empresa", lote_numero_raw=lote)


def test_pone_el_lote_id_de_su_numero() -> None:
    adjs = {"L1": [_adj("L1", "1"), _adj("L1", "2")]}

    resueltas, sin_lote = resolver_lotes_adjudicaciones(adjs, {"L1": {"1": 10, "2": 20}})

    assert [a.lote_id for a in adjs["L1"]] == [10, 20]
    assert (resueltas, sin_lote) == (2, 0)


def test_cuenta_las_que_se_quedan_sin_lote_en_un_multilote() -> None:
    adjs = {"L1": [_adj("L1", None), _adj("L1", "9")]}

    resueltas, sin_lote = resolver_lotes_adjudicaciones(adjs, {"L1": {"1": 10, "2": 20}})

    assert [a.lote_id for a in adjs["L1"]] == [None, None]
    assert (resueltas, sin_lote) == (0, 2)


def test_en_un_lote_unico_sin_referencia_no_falta_nada() -> None:
    """Con un solo lote, ``NULL`` es el «lote único implícito» de siempre."""
    adjs = {"L1": [_adj("L1", None)]}

    assert resolver_lotes_adjudicaciones(adjs, {"L1": {"1": 10}}) == (0, 0)


def test_sin_lotes_no_toca_las_adjudicaciones() -> None:
    adjs = {"L1": [_adj("L1", "1")]}

    assert resolver_lotes_adjudicaciones(adjs, {"L1": {}}) == (0, 0)
    assert adjs["L1"][0].lote_id is None
