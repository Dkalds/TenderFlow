"""Cobertura de la ficha nocturna: encaje tecnológico y reintentos de las fallidas.

Integración (``tmp_db``). ``list_pending_licitaciones`` pone, tras las reglas
de vigilancia, lo abierto con plazo que encaja con las tecnologías de alguna
organización, después lo demás abierto con plazo y al final lo cerrado. Y una
ficha ``failed`` solo vuelve al lote si su licitación sigue abierta (o tiene
favorito u oportunidad) y el fallo puede no repetirse.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from db.database import DocumentoReferencia, connect
from db.repositories.documentos import DocumentosRepository
from db.repositories.organizations import OrganizationRepository
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
from db.users import create_user

_HOY = datetime.now(UTC).date()
_EN_UN_MES = (_HOY + timedelta(days=30)).isoformat()
_VIGENTE = "tender-facts-test-v2"
_ANTERIOR = "tender-facts-test-v1"
_ERROR_PROVEEDOR = "El proveedor rechazó la API key (HTTP 401) para m: revisa la credencial"
_ERROR_SIN_PLIEGO = (
    "La licitación no referencia ningún pliego descargable; "
    "la ficha necesita al menos un documento adjunto en PLACSP."
)


def _sembrar(
    id_externo: str,
    *,
    estado: str | None = "PUB",
    fecha_limite: str | None = _EN_UN_MES,
    tecnologia: str | None = None,
    ml_tecnologias: str | None = None,
) -> None:
    """Una licitación con una página de pliego extraída (candidata a ficha)."""
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, estado, fecha_limite, "
            "tecnologia, ml_tecnologias, fecha_extraccion) "
            "VALUES (%s, 'Contrato', 'placsp', %s, %s, %s, %s, CURRENT_TIMESTAMP)",
            (id_externo, estado, fecha_limite, tecnologia, ml_tecnologias),
        )
    repo = DocumentosRepository()
    repo.upsert_meta(
        id_externo,
        [DocumentoReferencia(tipo="legal", uri=f"https://example.test/{id_externo}.pdf")],
    )
    doc = repo.list_by_licitacion(id_externo)[0]
    repo.mark_extracted(int(doc["id"]), texto="pliego", sha256=id_externo, pages=["pliego"])


def _organizacion(email: str, settings_json: str | None = None, **ajustes: object) -> int:
    user_id = create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email,
    )
    repo = OrganizationRepository()
    org_id = int(repo.ensure_personal_organization(user_id)["id"])
    if ajustes:
        repo.update_settings(org_id, dict(ajustes))
    if settings_json is not None:
        with connect() as c:
            c.execute(
                "UPDATE organizations SET settings_json = %s WHERE id = %s",
                (settings_json, org_id),
            )
    return org_id


def _fallida(licitacion_id: str, *, version: str, error: str) -> None:
    TenderFactSheetsRepository().upsert(
        licitacion_id=licitacion_id,
        status="failed",
        extraction_version=version,
        model="m",
        facts=None,
        field_count=0,
        evidence_count=0,
        error_detail=error,
    )


def _pendientes(**kwargs: object) -> list[str]:
    return TenderFactSheetsRepository().list_pending_licitaciones(
        extraction_version=_VIGENTE, limit=50, **kwargs
    )


@pytest.fixture()
def corpus(tmp_db):
    _sembrar("ENC-SAP", tecnologia="SAP, ERP")
    _sembrar("ENC-ML", ml_tecnologias="CRM,SAP")
    _sembrar("ENC-OTRA", tecnologia="CRM")
    _sembrar("ENC-CERRADA", estado="ADJ", tecnologia="SAP")
    _sembrar("ENC-VENCIDA", fecha_limite=(_HOY - timedelta(days=1)).isoformat(), tecnologia="SAP")
    return tmp_db


class TestEncajeTecnologico:
    def test_lo_que_encaja_va_antes_que_el_resto_de_lo_abierto(self, corpus):
        _organizacion("sap@example.test", tecnologias=["SAP"])

        pendientes = _pendientes()

        # Encaje por `tecnologia` (tech_priority 0) y por `ml_tecnologias`
        # (tech_priority 1); después lo abierto sin encaje; al final lo cerrado
        # y lo vencido, aunque sean SAP.
        assert pendientes[:3] == ["ENC-SAP", "ENC-ML", "ENC-OTRA"]
        assert set(pendientes[3:]) == {"ENC-CERRADA", "ENC-VENCIDA"}

    def test_sin_organizaciones_con_tecnologias_lo_abierto_va_por_su_orden(self, corpus):
        _organizacion("sin-tec@example.test", cpvs=["72"])

        pendientes = _pendientes()

        assert pendientes[:3] == ["ENC-OTRA", "ENC-SAP", "ENC-ML"]

    def test_se_juntan_las_tecnologias_de_todas_las_organizaciones(self, corpus):
        _organizacion("crm@example.test", tecnologias=["CRM"])
        _organizacion("sap@example.test", tecnologias=["SAP"])

        assert _pendientes()[:3] == ["ENC-OTRA", "ENC-SAP", "ENC-ML"]

    def test_un_settings_json_corrupto_no_tumba_el_lote(self, corpus):
        _organizacion("rota@example.test", settings_json='{"tecnologias": [')
        _organizacion("sap@example.test", tecnologias=["SAP"])

        assert _pendientes()[:3] == ["ENC-SAP", "ENC-ML", "ENC-OTRA"]


class TestReintentosDeLasFallidas:
    def test_version_anterior_y_abierta_vuelve_una_vez(self, tmp_db):
        _sembrar("FAL-ABIERTA")
        _fallida("FAL-ABIERTA", version=_ANTERIOR, error="El extractor no devolvió un objeto JSON")

        assert _pendientes() == ["FAL-ABIERTA"]

        # Reintentada con la versión vigente y vuelta a fallar: ya no entra.
        _fallida("FAL-ABIERTA", version=_VIGENTE, error="El extractor no devolvió un objeto JSON")
        assert _pendientes() == []

    def test_cerrada_no_vuelve_salvo_que_alguien_la_siga(self, tmp_db):
        _sembrar("FAL-CERRADA", estado="ADJ")
        _sembrar("FAL-FAVORITA", estado="ADJ")
        _fallida("FAL-CERRADA", version=_ANTERIOR, error="boom")
        _fallida("FAL-FAVORITA", version=_ANTERIOR, error="boom")
        with connect() as c:
            c.execute(
                "INSERT INTO watchlist_items (user_key, user_id, id_externo, organization_id) "
                "VALUES ('alguien', NULL, 'FAL-FAVORITA', NULL)"
            )

        assert _pendientes() == ["FAL-FAVORITA"]

    def test_json_roto_con_la_version_vigente_no_se_repite(self, tmp_db):
        _sembrar("FAL-JSON")
        _fallida("FAL-JSON", version=_VIGENTE, error="Expecting ',' delimiter: line 5 column 6")

        assert _pendientes(ahora=datetime.now(UTC) + timedelta(days=30)) == []

    def test_fallo_del_proveedor_vuelve_tras_la_espera(self, tmp_db):
        _sembrar("FAL-401")
        _fallida("FAL-401", version=_VIGENTE, error=_ERROR_PROVEEDOR)

        assert _pendientes(reintento_dias=7) == []
        assert _pendientes(reintento_dias=7, ahora=datetime.now(UTC) + timedelta(days=8)) == [
            "FAL-401"
        ]

    def test_fallo_de_documentos_espera_a_que_cambien(self, tmp_db):
        _sembrar("FAL-DOCS")
        # Versión anterior a propósito: un bump no arregla un pliego que falta.
        _fallida("FAL-DOCS", version=_ANTERIOR, error=_ERROR_SIN_PLIEGO)

        assert _pendientes() == []

        with connect() as c:
            c.execute(
                "UPDATE documentos SET updated_at = %s WHERE licitacion_id = 'FAL-DOCS'",
                ((datetime.now(UTC) + timedelta(minutes=1)).isoformat(),),
            )
        assert _pendientes() == ["FAL-DOCS"]

    def test_las_fallidas_van_tras_las_nunca_intentadas_de_su_nivel(self, tmp_db):
        _sembrar("FAL-VIEJA")
        _sembrar("NUEVA")
        _fallida("FAL-VIEJA", version=_ANTERIOR, error="boom")

        assert _pendientes() == ["NUEVA", "FAL-VIEJA"]
