"""Conector de la sindicación 1403 de PLACSP: consultas preliminares de mercado.

Apagado por defecto, como las sindicaciones 1143 y 1044. Lo que fija este
fichero:

- Una consulta entra en «Próximas» (estado ``CPM``) y **nunca** en el universo
  puntuable del Radar: su plazo es para responder, no para ofertar, y no va a
  ``fecha_limite``.
- Pasa la misma puerta tecnológica que PLACSP, sobre el objeto y no sobre el
  párrafo de la consulta.
- La clave lleva el órgano: «1/2026» lo usan cuatro órganos en la página medida.

La fixture es un recorte real del feed, bajado el 2026-10-31 (ver
``tests/fixtures/placsp_sindicaciones/README.md``). Los ``test_integration_*``
corren contra Postgres.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from scraper.connectors import REGISTERED_SOURCES_BY_ID
from scraper.connectors import placsp_consultas as consultas
from scraper.connectors.base import ParsedTender, RawNotice

_FIXTURES = Path(__file__).parent / "fixtures" / "placsp_sindicaciones"
_FICHERO = "consultas_1403.atom"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ESTADO = (
    "./{urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2}"
    "PreliminaryMarketConsultationStatus"
    "/{urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2}"
    "PreliminaryMarketConsultationStatusCode"
)

# Entradas de consultas_1403.atom, por posición.
_CIBERSEGURIDAD, _ATRM, _BOADILLA, _MICROSCOPIO, _PLANTAS_DE_AGUA = range(5)
_ID_CIBERSEGURIDAD = "placsp_consultas:51272410171001:24744/2026"
_ID_ATRM = "placsp_consultas:21261630169923:1/2026"
_ID_BOADILLA = "placsp_consultas:31018610145621:01/26 CM Boadilla"


def _entries() -> list[tuple[Any, str]]:
    raiz = etree.fromstring((_FIXTURES / _FICHERO).read_bytes())
    return [
        (entry, entry.findtext(f"{_ATOM_NS}updated") or "")
        for entry in raiz.findall(f"{_ATOM_NS}entry")
    ]


def _parsear(entry: Any, updated: str) -> tuple[ParsedTender | None, Any]:
    conector = consultas.PlacspConsultasConnector(consultas.URL_SINDICACION_1403)
    return conector.parse(RawNotice(natural_id=updated, payload=(entry, updated))), conector


def _licitacion(posicion: int) -> Any:
    parsed, _ = _parsear(*_entries()[posicion])
    assert parsed is not None
    return parsed.licitacion


@pytest.fixture()
def feed(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """``iter_live_entries`` servido desde la fixture."""
    estado: dict[str, Any] = {"llamadas": []}

    def iter_live_entries(**kw: Any) -> tuple[list[tuple[Any, str]], dict[str, Any]]:
        estado["llamadas"].append(kw)
        entries = _entries()
        meta = {"newest_updated": max(u for _, u in entries), "etag": '"e1"', "last_modified": None}
        return entries, meta

    monkeypatch.setattr("scraper.atom_live.iter_live_entries", iter_live_entries)
    return estado


# ── El modelado ──────────────────────────────────────────────────────────────


def test_una_consulta_entra_en_proximas_sin_plazo_de_ofertas():
    lic = _licitacion(_CIBERSEGURIDAD)

    assert lic.id_externo == _ID_CIBERSEGURIDAD
    assert lic.fuente == "placsp_consultas"
    assert lic.estado == "CPM"
    assert lic.fecha_limite is None
    assert lic.fecha_inicio is None
    assert lic.titulo == "Servicios de ciberseguridad"
    assert lic.fecha_publicacion == "2026-10-30"
    assert lic.tipos_anuncio == "DOC_CON"
    assert lic.analysis_universe == "technology_observed"


def test_el_plazo_para_responder_viaja_en_la_descripcion():
    lic = _licitacion(_CIBERSEGURIDAD)

    assert lic.descripcion.startswith("Conocer la capacidad y la estructura del mercado")
    assert lic.descripcion.endswith("Plazo para responder a la consulta: 2026-11-10.")


def test_una_consulta_realizada_sigue_en_proximas():
    """``REA``: la consulta terminó, la licitación aún no ha salido."""
    lic = _licitacion(_BOADILLA)

    assert lic.id_externo == _ID_BOADILLA
    assert lic.estado == "CPM"


def test_una_consulta_anulada_se_guarda_cerrada():
    from shared.estados import ESTADOS_CERRADOS

    entry, updated = _entries()[_CIBERSEGURIDAD]
    entry.find(_ESTADO).text = "ANU"
    parsed, _ = _parsear(entry, updated)

    assert parsed is not None
    assert parsed.licitacion.estado == "ANUL"
    assert parsed.licitacion.estado in ESTADOS_CERRADOS


def test_el_organo_se_lee_del_bloque_de_la_consulta():
    lic = _licitacion(_ATRM)

    assert lic.organo_contratacion == "Agencia Tributaria de la Región de Murcia (ATRM)"
    assert lic.organo_ref_fuente == "21261630169923"


# ── La puerta tecnológica ────────────────────────────────────────────────────


def test_entra_por_keyword_con_su_etiqueta():
    lic = _licitacion(_CIBERSEGURIDAD)

    assert lic.inclusion_reason == "keyword"
    assert lic.tecnologia == "CIBERSEGURIDAD"
    assert lic.cpv is None


def test_entra_por_cpv_del_universo():
    lic = _licitacion(_ATRM)

    assert lic.cpv == "72263000"
    assert lic.inclusion_reason in ("keyword", "cpv_ti")


@pytest.mark.parametrize("posicion", [_MICROSCOPIO, _PLANTAS_DE_AGUA])
def test_sin_senal_en_el_objeto_se_descarta_y_se_cuenta(posicion):
    """El microscopio entraba como ``CLOUD_INFRA`` si la puerta leía el párrafo."""
    parsed, conector = _parsear(*_entries()[posicion])

    assert parsed is None
    assert conector.contadores_de_descarte()["placsp_consultas_sin_senal_tecnologica"] == 1


# ── Identidad ────────────────────────────────────────────────────────────────


def test_la_clave_acota_el_identificador_por_organo():
    """«1/2026» lo publican cuatro órganos en la página medida."""
    assert _licitacion(_ATRM).id_externo == _ID_ATRM


def test_la_clave_es_estable_entre_pasadas():
    assert _licitacion(_ATRM).id_externo == _licitacion(_ATRM).id_externo


def test_el_expediente_natural_incluye_el_organo():
    from services.dedupe import natural_expediente

    assert natural_expediente(_ID_ATRM) == "21261630169923:1/2026"


def test_una_entrada_sin_identificador_de_organo_se_descarta_y_se_cuenta():
    entry, updated = _entries()[_CIBERSEGURIDAD]
    for nodo in entry.iter("{*}PartyIdentification"):
        nodo.getparent().remove(nodo)
    parsed, conector = _parsear(entry, updated)

    assert parsed is None
    assert conector.contadores_de_descarte()["placsp_consultas_sin_identificador_de_organo"] == 1


# ── Apagada por defecto ──────────────────────────────────────────────────────


def test_sin_su_variable_la_fuente_se_declara_apagada_y_no_descarga(monkeypatch, feed):
    from config import settings

    assert settings.__class__.model_fields[consultas.VARIABLE].default == ""
    monkeypatch.setattr(settings, consultas.VARIABLE, "")
    apagadas: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "scraper.connectors.base.record_source_disabled",
        lambda source_id, *, motivo: apagadas.append((source_id, motivo)),
    )

    assert consultas.ejecutar() is None

    assert [s for s, _ in apagadas] == [consultas.SOURCE_ID]
    assert consultas.VARIABLE in apagadas[0][1]
    assert feed["llamadas"] == []


def test_esta_registrada_como_opcional():
    fuente = REGISTERED_SOURCES_BY_ID[consultas.SOURCE_ID]

    assert fuente.estado == "opcional"
    assert fuente.modulo == consultas.__name__
    assert "apagad" in fuente.alcance.lower()


def test_la_url_documentada_es_la_de_la_sindicacion():
    from scraper.atom_live import _is_allowed_url, _parse_feed_links

    assert consultas.URL_SINDICACION_1403.endswith("sindicacion_1403/CPM_SectorPublico.atom")
    assert _is_allowed_url(consultas.URL_SINDICACION_1403)
    siguiente = _parse_feed_links(etree.fromstring((_FIXTURES / _FICHERO).read_bytes()))
    assert siguiente is not None
    assert _is_allowed_url(siguiente)


def test_check_valida_la_primera_pagina_sin_escribir(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from scraper.connectors import sindicacion_placsp

    registro = MagicMock()
    monkeypatch.setattr(sindicacion_placsp, "log", registro)
    contenido = (_FIXTURES / _FICHERO).read_bytes()
    pedidas: list[str] = []

    class _Pagina:
        content = contenido

    def fetch_atom_page(url: str, **kw: Any) -> _Pagina:
        pedidas.append(url)
        return _Pagina()

    monkeypatch.setattr("scraper.atom_live.fetch_atom_page", fetch_atom_page)
    monkeypatch.setattr(
        "scraper.connectors.base.run_connector",
        lambda *a, **k: pytest.fail("--check no puede ingerir"),
    )

    assert consultas.main(["--check"]) == 0

    assert pedidas == [consultas.URL_SINDICACION_1403]
    informe = next(
        c.kwargs for c in registro.info.call_args_list if c.args == ("sindicacion_check",)
    )
    assert (informe["entradas"], informe["admitidas"]) == (5, 3)


# ---------------------------------------------------------------------------
# Recorrido real contra Postgres
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def test_integration_las_consultas_salen_en_proximas_y_no_en_el_radar(db, feed):
    from db.repositories.aggregates import AggregateRepository
    from db.repositories.licitaciones import LicitacionRepository
    from scraper.connectors.base import run_connector
    from services.classification import ESTADOS_PRE_LICITACION

    conector = consultas.PlacspConsultasConnector(consultas.URL_SINDICACION_1403)
    resultado = run_connector(conector)
    # La segunda pasada no duplica: misma clave, mismo upsert.
    run_connector(consultas.PlacspConsultasConnector(consultas.URL_SINDICACION_1403))

    assert (resultado.parsed, resultado.descartadas, resultado.errores) == (3, 2, 0)
    ids = {_ID_CIBERSEGURIDAD, _ID_ATRM, _ID_BOADILLA}
    proximas, total, _ = LicitacionRepository().proximas(estados=ESTADOS_PRE_LICITACION)
    assert {str(f["id_externo"]) for f in proximas} == ids
    assert total == 3
    # Con el plazo de respuesta todavía vivo el día de la fixture.
    radar = AggregateRepository().scoring_candidates(hoy_iso="2026-10-31")
    assert not ids & {str(r["id_externo"]) for r in radar}
