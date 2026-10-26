"""La ficha nocturna va primero a lo que casa con una regla de vigilancia (D52).

Integración (``tmp_db``). El orden de ``list_pending_licitaciones`` es
oportunidad abierta → favorito → **abierta con plazo que casa con alguna regla
activa** → el resto. El casado no es un matcher nuevo: es
``services.watchlist_rules._rule_clauses`` acotado a «abierta con plazo
vigente» (``mcp_server/glosario.md`` §3), así que una regla avisa y prioriza
exactamente las mismas filas.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from db.database import DocumentoReferencia, connect
from db.repositories.documentos import DocumentosRepository
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
from services.watchlist_rules import (
    WatchlistRule,
    create_rule,
    ids_abiertas_que_casan,
    reglas_activas,
)

_HOY = datetime.now(UTC).date()
_EN_UN_MES = (_HOY + timedelta(days=30)).isoformat()
_AYER = (_HOY - timedelta(days=1)).isoformat()
_VERSION = "tender-facts-test"


def _sembrar(id_externo: str, *, titulo: str, estado: str | None, fecha_limite: str) -> None:
    """Una licitación con una página de pliego extraída (candidata a ficha)."""
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, estado, fecha_limite, "
            "fecha_extraccion) VALUES (%s, %s, 'placsp', %s, %s, CURRENT_TIMESTAMP)",
            (id_externo, titulo, estado, fecha_limite),
        )
    repo = DocumentosRepository()
    repo.upsert_meta(
        id_externo,
        [DocumentoReferencia(tipo="legal", uri=f"https://example.test/{id_externo}.pdf")],
    )
    doc = repo.list_by_licitacion(id_externo)[0]
    repo.mark_extracted(int(doc["id"]), texto="pliego", sha256=id_externo, pages=["pliego"])


@pytest.fixture()
def corpus(tmp_db):
    """Cinco candidatas; solo ``PRI-REGLA`` es abierta, en plazo y casa con «backup»."""
    _sembrar("PRI-OTRA", titulo="Suministro de mobiliario", estado="PUB", fecha_limite=_EN_UN_MES)
    _sembrar(
        "PRI-REGLA", titulo="Servicio de backup gestionado", estado="PUB", fecha_limite=_EN_UN_MES
    )
    _sembrar("PRI-CERRADA", titulo="Backup ya adjudicado", estado="ADJ", fecha_limite=_EN_UN_MES)
    _sembrar("PRI-VENCIDA", titulo="Backup con el plazo vencido", estado="PUB", fecha_limite=_AYER)
    _sembrar("PRI-FAVORITA", titulo="Limpieza de oficinas", estado="PUB", fecha_limite=_EN_UN_MES)
    with connect() as c:
        c.execute(
            "INSERT INTO watchlist_items (user_key, user_id, id_externo, organization_id) "
            "VALUES (%s, NULL, %s, NULL)",
            ("alguien", "PRI-FAVORITA"),
        )
    return tmp_db


def test_el_casado_es_abierta_con_plazo_y_el_predicado_de_la_regla(corpus):
    ids = ids_abiertas_que_casan([WatchlistRule(keyword="backup")])

    assert ids == ["PRI-REGLA"]


def test_sin_reglas_no_casa_nada(corpus):
    assert ids_abiertas_que_casan([]) == []


def test_varias_reglas_se_unen_sin_repetir(corpus):
    ids = ids_abiertas_que_casan(
        [WatchlistRule(keyword="backup"), WatchlistRule(keyword="gestionado")]
    )

    assert ids == ["PRI-REGLA"]


def test_lo_que_casa_va_tras_el_favorito_y_antes_del_resto(corpus):
    casan = ids_abiertas_que_casan([WatchlistRule(keyword="backup")])

    pendientes = TenderFactSheetsRepository().list_pending_licitaciones(
        extraction_version=_VERSION, limit=10, casan_regla=casan
    )

    assert pendientes[:2] == ["PRI-FAVORITA", "PRI-REGLA"]
    assert set(pendientes[2:]) == {"PRI-OTRA", "PRI-CERRADA", "PRI-VENCIDA"}


def test_sin_casado_el_orden_es_el_de_antes(corpus):
    pendientes = TenderFactSheetsRepository().list_pending_licitaciones(
        extraction_version=_VERSION, limit=10
    )

    assert pendientes[0] == "PRI-FAVORITA"
    # Sin nivel de regla, PRI-REGLA no adelanta a nadie: el resto va por id.
    assert pendientes[1:] == sorted(pendientes[1:])


def test_solo_cuentan_las_reglas_activas(corpus):
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    user_id = create_user(
        email="ficha-reglas@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
        display_name="Dueña de las reglas",
    )
    org_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    create_rule(
        "ficha-reglas",
        WatchlistRule(keyword="backup"),
        user_id=user_id,
        organization_id=org_id,
    )
    create_rule(
        "ficha-reglas",
        WatchlistRule(keyword="mobiliario", active=False),
        user_id=user_id,
        organization_id=org_id,
    )

    activas = reglas_activas()

    assert [r.keyword for r in activas] == ["backup"]
    assert ids_abiertas_que_casan() == ["PRI-REGLA"]
