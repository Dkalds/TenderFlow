"""La división CPV 32 (telecomunicaciones) entra en el universo de ingesta (2026-10-30).

Un aviso con CPV 32 se guarda aunque el título no case con el diccionario, como
ya pasaba con 48/72, en todas las fuentes con CPV: la puerta tecnológica (PSCP,
contratos menores de PLACSP), el rescate por CPV del feed de PLACSP y la query
de TED. Lo que **no** cambia: la 32 no corrobora keywords ambiguas ni entra en
la población del clasificador, que se entrenó con 48/72.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from lxml import etree

from scraper.connectors.base import RawNotice

_CBC = "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
_CAC = "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
_CACEXT = "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2"


def _entry(*cpvs: str) -> etree._Element:
    """Una ``<entry>`` con solo los CPV del proyecto, que es lo que mira el filtro."""
    clasificaciones = "".join(
        "<cac:RequiredCommodityClassification>"
        f"<cbc:ItemClassificationCode>{cpv}</cbc:ItemClassificationCode>"
        "</cac:RequiredCommodityClassification>"
        for cpv in cpvs
    )
    xml = (
        f'<entry xmlns="http://www.w3.org/2005/Atom" xmlns:cbc="{_CBC}" '
        f'xmlns:cac="{_CAC}" xmlns:cacext="{_CACEXT}">'
        "<cacext:ContractFolderStatus><cac:ProcurementProject>"
        f"{clasificaciones}"
        "</cac:ProcurementProject></cacext:ContractFolderStatus></entry>"
    )
    return etree.fromstring(xml.encode())


class TestPuerta:
    def test_cpv_32_sin_keyword_entra_sin_etiquetas(self) -> None:
        from scraper.puerta_tecnologica import MOTIVO_CPV_TI, senal_tecnologica

        senal = senal_tecnologica("Subministrament d'equips de radiocomunicació", "32344000-8")
        assert senal.motivo == MOTIVO_CPV_TI
        assert senal.tecnologias == ()

    def test_cpv_32_no_corrobora_una_ambigua(self) -> None:
        """CCTV (32323500) con «seguridad perimetral» es seguridad física."""
        from scraper.puerta_tecnologica import MOTIVO_AMBIGUA_SIN_CPV_TI, senal_tecnologica

        senal = senal_tecnologica("Mejora de la seguridad perimetral del depósito", "32323500")
        assert senal.motivo == MOTIVO_AMBIGUA_SIN_CPV_TI

    def test_fuera_del_universo_sigue_fuera(self) -> None:
        from scraper.puerta_tecnologica import MOTIVO_SIN_SENAL, senal_tecnologica

        assert senal_tecnologica("Suministro de mobiliario", "39100000").motivo == MOTIVO_SIN_SENAL


class TestRescatePlacsp:
    def test_cpv_32_se_guarda_como_universo_sin_puntuar(self) -> None:
        """La 32 no es población del modelo: ni se carga ni se le pide nada."""
        from scraper.pipeline import INCLUSION_CPV_TI, _ml_classify_entry

        entry = MagicMock()
        entry.xpath.return_value = ["32412100"]
        lic = MagicMock()
        with (
            patch("scraper.pipeline.parse_entry_unfiltered", return_value=lic),
            patch("scraper.pipeline._get_ml_clf") as get_clf,
        ):
            assert _ml_classify_entry(entry) is lic
        assert lic.inclusion_reason == INCLUSION_CPV_TI
        get_clf.assert_not_called()


class TestTed:
    def test_la_query_por_defecto_incluye_la_32(self) -> None:
        from scraper.connectors.ted import TedConnector

        q = TedConnector()._build_query("20260101")
        for familia in ("48", "72", "32"):
            assert f"classification-cpv IN ({familia}*)" in q


class TestBackfillSoloCpv:
    def test_descarta_sin_parsear_lo_que_no_es_de_la_familia(self) -> None:
        from scraper.connectors.placsp import PlacspBulkConnector

        conector = PlacspBulkConnector(2026, 10, solo_cpv=("32",))
        conector._core = MagicMock()
        assert conector.parse(RawNotice("f", (_entry("72267000-4"), None))) is None
        conector._core.parse_entry_elem.assert_not_called()

    def test_lo_de_la_familia_sigue_la_regla_de_siempre(self) -> None:
        """Basta un CPV del proyecto; lo que entre lo decide el núcleo de siempre."""
        from scraper.connectors.placsp import PlacspBulkConnector

        conector = PlacspBulkConnector(2026, 10, solo_cpv=("32",))
        conector._core = MagicMock()
        entry = _entry("45000000-7", "32412100-5")
        conector.parse(RawNotice("f", (entry, None)))
        conector._core.parse_entry_elem.assert_called_once_with(
            entry, fuente="bulk_202610", updated_str=None
        )

    def test_sin_filtro_parsea_todo(self) -> None:
        from scraper.connectors.placsp import PlacspBulkConnector

        conector = PlacspBulkConnector(2026, 10)
        conector._core = MagicMock()
        conector.parse(RawNotice("f", (_entry("90910000-9"), None)))
        conector._core.parse_entry_elem.assert_called_once()


_FICHA_PSCP = (
    "https://contractaciopublica.cat/ca/detall-publicacio/0a1b2c3d-4e5f-6789-abcd-ef0123456789/123"
)


class _SesionFalsa:
    """Una página de Socrata con un registro; guarda los parámetros pedidos."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def get(self, url: str, *, params: dict[str, str], headers: Any, timeout: Any) -> Any:
        self.calls.append(params)
        respuesta = MagicMock()
        respuesta.json.return_value = [
            {
                "codi_expedient": "X-1",
                "enllac_publicacio": {"url": _FICHA_PSCP},
                ":updated_at": "2026-10-01T00:00:00.000Z",
                ":id": "row-1",
            }
        ]
        return respuesta


class TestBackfillPscp:
    def test_la_consulta_filtra_por_la_familia_en_el_servidor(self) -> None:
        """`codi_cpv` es `32420000-3||72000000-5`: la familia puede ir en cualquier posición."""
        from scraper.connectors.pscp import PscpConnector

        sesion = _SesionFalsa()
        conector = PscpConnector(dataset_id="abcd-1234", session=sesion, solo_cpv=("32",))
        list(conector.fetch({"last_seen_updated": "2000-01-01"}))
        where = sesion.calls[0]["$where"]
        assert ":updated_at >= '2000-01-01'" in where
        assert "codi_cpv like '32%' OR codi_cpv like '%||32%'" in where

    def test_una_pasada_filtrada_no_mueve_el_cursor(self) -> None:
        """Su marca más alta saltaría las filas de otras familias aún sin leer."""
        from scraper.connectors.pscp import PscpConnector

        conector = PscpConnector(dataset_id="abcd-1234", session=_SesionFalsa(), solo_cpv=("32",))
        list(conector.fetch({"last_seen_updated": "2000-01-01"}))
        assert conector.new_cursor() is None

    def test_sin_filtro_la_consulta_y_el_cursor_no_cambian(self) -> None:
        from scraper.connectors.pscp import PscpConnector

        sesion = _SesionFalsa()
        conector = PscpConnector(dataset_id="abcd-1234", session=sesion)
        list(conector.fetch({"last_seen_updated": "2026-09-01"}))
        assert "codi_cpv" not in sesion.calls[0]["$where"]
        assert conector.new_cursor() is not None

    def test_solo_admite_prefijos_numericos(self) -> None:
        """El prefijo va dentro del `$where`."""
        from scraper.connectors.pscp import PscpConnector

        with pytest.raises(ValueError, match="numéricos"):
            PscpConnector(dataset_id="abcd-1234", solo_cpv=("32' OR 1=1 --",))


def test_el_universo_entra_en_filter_version() -> None:
    """Con otro universo, las mismas keywords no dejan entrar lo mismo."""
    import services.tecnologias_diccionario as mod

    diccionario = {"SAP": ["sap hana"]}
    antes = mod._hash_de(diccionario)
    with patch.object(mod, "CPV_PREFIXES_UNIVERSO", ["48", "72"]):
        assert mod._hash_de(diccionario) != antes
