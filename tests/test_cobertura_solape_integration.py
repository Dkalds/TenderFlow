"""Medición del solape autonómico y allowlist de documentos derivada del inventario (2026-09-14)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from db.repositories.cobertura import organos_por_fuente, solape_por_ccaa
from db.upsert import Licitacion, upsert_licitaciones
from scraper.connectors import REGISTERED_SOURCES, dominios_documentos_por_defecto
from scripts.medir_solape_agregados import CCAA_D16, render_markdown

_HOY = datetime.now(UTC).date()


def _lic(
    id_externo: str,
    *,
    ccaa: str,
    fuente: str,
    estado: str = "PUB",
    tecnologia: str | None = "SAP",
    universo: str | None = "technology_observed",
    organo: str = "Ayuntamiento de Prueba",
    dias: int = 30,
) -> Licitacion:
    return Licitacion(
        id_externo=id_externo,
        titulo=f"Expediente {id_externo}",
        organo_contratacion=organo,
        ccaa=ccaa,
        fuente=fuente,
        estado=estado,
        tecnologia=tecnologia,
        analysis_universe=universo,
        fecha_publicacion=(_HOY - timedelta(days=dias)).isoformat(),
    )


@pytest.fixture()
def corpus(tmp_db):
    upsert_licitaciones(
        [
            # Madrid: dos TI directas por PLACSP, una TI agregada, una fuera del universo.
            _lic("MAD-1", ccaa="Madrid", fuente="placsp"),
            _lic("MAD-2", ccaa="Madrid", fuente="placsp", organo="Comunidad de Madrid"),
            _lic(
                "MAD-3", ccaa="Madrid", fuente="placsp", estado="AGR", organo="Comunidad de Madrid"
            ),
            _lic("MAD-4", ccaa="Madrid", fuente="pscp", tecnologia=None, universo="pscp_observed"),
            # Andalucía: una TI agregada, una antigua fuera de ventana.
            _lic("AND-1", ccaa="Andalucía", fuente="placsp", estado="AGR"),
            _lic("AND-2", ccaa="Andalucía", fuente="placsp", dias=800),
            # Cataluña vía PSCP con etiqueta: entra al universo por `tecnologia`.
            _lic("CAT-1", ccaa="Cataluña", fuente="pscp", universo="pscp_observed"),
        ]
    )
    return tmp_db


def test_solape_por_ccaa_cuenta_universo_y_agregados(corpus) -> None:
    filas = {f.ccaa: f for f in solape_por_ccaa(desde=_HOY - timedelta(days=365))}

    madrid = filas["Madrid"]
    assert madrid.total == 4
    assert madrid.universo_ti == 3
    assert madrid.universo_ti_agregados == 1
    assert madrid.pct_agregados == pytest.approx(33.3)
    assert madrid.universo_ti_por_fuente == {"placsp": 3}

    andalucia = filas["Andalucía"]
    assert andalucia.total == 1  # la de hace 800 días queda fuera de la ventana
    assert andalucia.universo_ti_agregados == 1
    assert andalucia.pct_agregados == 100.0

    assert filas["Cataluña"].universo_ti == 1
    assert filas["Cataluña"].universo_ti_por_fuente == {"pscp": 1}


def test_organos_por_fuente_agrupa_por_texto_sin_maestro(corpus) -> None:
    organos = organos_por_fuente(ccaa="Madrid", desde=_HOY - timedelta(days=365), limit=15)
    assert [o.organo for o in organos] == ["Comunidad de Madrid", "Ayuntamiento de Prueba"]
    assert organos[0].expedientes == 2
    assert organos[0].fuentes == {"placsp": 2}


def test_sin_filas_devuelve_listas_vacias(tmp_db) -> None:
    assert solape_por_ccaa(desde=date(2020, 1, 1)) == []
    assert organos_por_fuente(ccaa="Madrid", desde=date(2020, 1, 1)) == []


def test_render_markdown_es_legible_sin_bd() -> None:
    texto = render_markdown(
        desde=date(2025, 9, 1),
        filas=[
            {
                "ccaa": "Madrid",
                "total": 10,
                "universo_ti": 4,
                "universo_ti_agregados": 3,
                "pct_agregados": 75.0,
                "universo_ti_por_fuente": {"placsp": 4},
            }
        ],
        organos={
            "Madrid": [],
            "Andalucía": [{"organo": "Junta", "expedientes": 2, "fuentes": {"placsp": 2}}],
        },
    )
    assert "| Madrid | 10 | 4 | 3 | 75.0 % | placsp 4 |" in texto
    assert "_Sin expedientes TI en la ventana._" in texto
    assert "| Junta | 2 | placsp 2 |" in texto
    assert CCAA_D16 == ("Madrid", "Andalucía", "Comunidad Valenciana")


def test_allowlist_de_documentos_por_defecto_sale_del_inventario() -> None:
    """El literal de settings y el inventario de fuentes no pueden divergir."""
    from config import settings

    literal = tuple(h.strip() for h in settings.DOCUMENT_ALLOWED_HOSTS.split(",") if h.strip())
    assert literal == dominios_documentos_por_defecto()
    # Toda fuente que declare dominios está representada; hoy solo PLACSP los emite.
    for fuente in REGISTERED_SOURCES:
        if fuente.estado != "fuera_de_alcance":
            for dominio in fuente.dominios_documentos:
                assert dominio in literal


def test_allowlist_por_defecto_rechaza_host_ajeno() -> None:
    from shared.ssrf import validate_outbound_url

    with pytest.raises(ValueError, match="allowlist"):
        validate_outbound_url(
            "https://portal-ajeno.example/pliego.pdf",
            allowed_hosts=dominios_documentos_por_defecto(),
        )
