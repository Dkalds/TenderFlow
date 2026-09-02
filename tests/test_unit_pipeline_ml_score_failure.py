"""Si el modelo revienta al puntuar, la entrada CPV 48/72 se conserva igual.

Antes de 2026-09 ese fallo devolvía ``None`` y la licitación se perdía: un
modelo roto vaciaba la ingesta de TI en silencio. Ahora el universo CPV no
depende del modelo; el ``ml_proba`` queda sin rellenar y el motivo de inclusión
es el del universo, no el del rescate.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import scraper.pipeline as pipeline


def test_un_fallo_al_puntuar_conserva_la_entrada_como_universo_cpv() -> None:
    entry = MagicMock()
    entry.xpath.return_value = ["72267100-0"]
    lic = SimpleNamespace(
        id_externo="L1",
        titulo="Mantenimiento de un ERP",
        descripcion="",
        cpv="72267100-0",
        importe=1000.0,
        inclusion_reason=None,
        ml_proba=None,
    )
    clf = MagicMock()
    clf.pipeline.predict_proba.side_effect = RuntimeError("modelo corrupto")

    with (
        patch.object(pipeline, "parse_entry_unfiltered", return_value=lic),
        patch.object(pipeline, "_get_ml_clf", return_value=clf),
    ):
        resultado = pipeline._ml_classify_entry(entry)

    assert resultado is lic
    assert lic.inclusion_reason == pipeline.INCLUSION_CPV_TI
    assert lic.ml_proba is None


def test_fuera_de_cpv_ti_no_se_parsea_siquiera() -> None:
    entry = MagicMock()
    entry.xpath.return_value = ["33696500-0"]  # reactivos de laboratorio
    with patch.object(pipeline, "parse_entry_unfiltered") as parse:
        assert pipeline._ml_classify_entry(entry) is None
    parse.assert_not_called()
