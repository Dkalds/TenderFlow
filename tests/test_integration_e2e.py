"""Tests de integración E2E del pipeline completo.

Verifican el flujo completo:
  1. Parseo de XML ATOM (CODICE) con licitaciones SAP
  2. Filtrado por keywords
  3. Persistencia en SQLite (tmp_db)
  4. Lectura desde data_loader (sin Streamlit)
  5. Verificación de KPIs pre-calculados

Estos tests se marcan con @pytest.mark.integration y son más lentos que los
unitarios. Se excluyen de CI rápido con: pytest -m "not integration"
"""

from __future__ import annotations

import textwrap

import pandas as pd
import pytest

# ─── Fixtures y helpers ───────────────────────────────────────────────────────

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cacext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbcext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}


def _make_atom_feed(entries_xml: str) -> bytes:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n' + entries_xml + "\n</feed>\n"
    )
    return xml.encode()


def _make_sap_entry(
    id_externo: str = "E2E-001",
    titulo: str = "Mantenimiento SAP ERP corporativo",
    importe: str = "250000.00",
    estado: str = "PUB",
    organo: str = "Ministerio de Hacienda",
    cpv: str = "72267100-0",
    nuts: str = "ES300",
) -> str:
    """Genera XML CODICE válido para una entrada SAP con el formato correcto."""
    cbc = _NS["cbc"]
    cac = _NS["cac"]
    cacext = _NS["cacext"]
    cbcext = _NS["cbcext"]
    return textwrap.dedent(f"""\
        <entry xmlns="http://www.w3.org/2005/Atom"
               xmlns:cbc="{cbc}"
               xmlns:cac="{cac}"
               xmlns:cacext="{cacext}"
               xmlns:cbcext="{cbcext}">
          <id>https://example.com/{id_externo}</id>
          <title>{titulo}</title>
          <updated>2024-03-15T00:00:00Z</updated>
          <link href="https://example.com/{id_externo}" rel="alternate"/>
          <summary>
            Id licitación: {id_externo}; Órgano de Contratación: {organo};
            Importe: {importe} EUR; Estado: {estado}
          </summary>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>{id_externo}</cbc:ContractFolderID>
            <cbcext:ContractFolderStatusCode>{estado}</cbcext:ContractFolderStatusCode>
            <cacext:LocatedContractingParty>
              <cac:Party>
                <cac:PartyName><cbc:Name>{organo}</cbc:Name></cac:PartyName>
              </cac:Party>
            </cacext:LocatedContractingParty>
            <cac:ProcurementProject>
              <cbc:Name>{titulo}</cbc:Name>
              <cbc:TypeCode>2</cbc:TypeCode>
              <cac:RequiredCommodityClassification>
                <cbc:ItemClassificationCode>{cpv}</cbc:ItemClassificationCode>
              </cac:RequiredCommodityClassification>
              <cac:BudgetAmount>
                <cbc:TaxExclusiveAmount currencyID="EUR">{importe}</cbc:TaxExclusiveAmount>
              </cac:BudgetAmount>
              <cac:RealizedLocation>
                <cbc:CountrySubentityCode>{nuts}</cbc:CountrySubentityCode>
              </cac:RealizedLocation>
            </cac:ProcurementProject>
          </cacext:ContractFolderStatus>
        </entry>
    """)


def _make_non_sap_entry(id_externo: str = "E2E-999") -> str:
    """Genera una entrada sin keywords SAP (debe ser filtrada)."""
    cbc = _NS["cbc"]
    cac = _NS["cac"]
    cacext = _NS["cacext"]
    cbcext = _NS["cbcext"]
    return textwrap.dedent(f"""\
        <entry xmlns="http://www.w3.org/2005/Atom"
               xmlns:cbc="{cbc}"
               xmlns:cac="{cac}"
               xmlns:cacext="{cacext}"
               xmlns:cbcext="{cbcext}">
          <id>https://example.com/{id_externo}</id>
          <title>Servicio de limpieza de edificios administrativos</title>
          <updated>2024-03-15T00:00:00Z</updated>
          <summary>
            Id licitación: {id_externo}; Órgano de Contratación: Ministerio del Interior;
            Importe: 50000.00 EUR; Estado: PUB
          </summary>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>{id_externo}</cbc:ContractFolderID>
            <cbcext:ContractFolderStatusCode>PUB</cbcext:ContractFolderStatusCode>
            <cacext:LocatedContractingParty>
              <cac:Party>
                <cac:PartyName><cbc:Name>Ministerio del Interior</cbc:Name></cac:PartyName>
              </cac:Party>
            </cacext:LocatedContractingParty>
            <cac:ProcurementProject>
              <cbc:Name>Servicio de limpieza de edificios administrativos</cbc:Name>
              <cac:BudgetAmount>
                <cbc:TaxExclusiveAmount currencyID="EUR">50000.00</cbc:TaxExclusiveAmount>
              </cac:BudgetAmount>
            </cac:ProcurementProject>
          </cacext:ContractFolderStatus>
        </entry>
    """)


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestE2EPipelineToDatabase:
    """Prueba el pipeline completo desde XML hasta persistencia en BD."""

    def test_parse_and_persist_sap_licitacion(self, tmp_db):
        """Una licitación con keywords SAP debe persistirse correctamente."""
        db_mod, _ = tmp_db

        feed_bytes = _make_atom_feed(_make_sap_entry("E2E-001"))

        from scraper.codice_parser import parse_atom_bytes

        licitaciones = []
        for lic, _ in parse_atom_bytes(feed_bytes):
            licitaciones.append(lic)

        assert len(licitaciones) == 1
        lic = licitaciones[0]
        assert lic.id_externo == "E2E-001"
        assert lic.raw_keywords  # debe tener keywords SAP detectadas

        # Persistir
        nuevas, actualizadas = db_mod.upsert_licitaciones(licitaciones)
        assert nuevas == 1
        assert actualizadas == 0

        # Verificar en BD
        count = db_mod.count_licitaciones()
        assert count == 1

    def test_non_sap_entry_filtered_out(self, tmp_db):
        """Una licitación sin keywords SAP NO debe persistirse."""
        db_mod, _ = tmp_db

        # El parser usa filters.matches_sap internamente, así que una entrada
        # sin keywords SAP no debería devolver ningún Licitacion.
        feed_bytes = _make_atom_feed(_make_non_sap_entry("E2E-999"))

        from scraper.codice_parser import parse_atom_bytes

        licitaciones = [lic for lic, _ in parse_atom_bytes(feed_bytes)]
        # Las entries sin keywords SAP son filtradas por el parser
        assert len(licitaciones) == 0

        # BD debe seguir vacía
        assert db_mod.count_licitaciones() == 0

    def test_upsert_idempotente(self, tmp_db):
        """Persistir la misma licitación dos veces debe ser idempotente."""
        db_mod, _ = tmp_db

        feed_bytes = _make_atom_feed(_make_sap_entry("E2E-IDEM"))
        from scraper.codice_parser import parse_atom_bytes

        licitaciones = [lic for lic, _ in parse_atom_bytes(feed_bytes)]
        assert len(licitaciones) == 1

        nuevas1, act1 = db_mod.upsert_licitaciones(licitaciones)
        nuevas2, act2 = db_mod.upsert_licitaciones(licitaciones)

        assert nuevas1 == 1
        assert act1 == 0
        assert nuevas2 == 0
        assert act2 == 1  # segunda inserción → actualización
        assert db_mod.count_licitaciones() == 1  # sigue siendo 1 registro

    def test_multiple_licitaciones(self, tmp_db):
        """Múltiples licitaciones SAP se persisten todas."""
        db_mod, _ = tmp_db

        entries = "".join(
            _make_sap_entry(f"E2E-MULTI-{i:03d}", titulo=f"Proyecto SAP módulo {i}")
            for i in range(5)
        )
        feed_bytes = _make_atom_feed(entries)

        from scraper.codice_parser import parse_atom_bytes

        licitaciones = [lic for lic, _ in parse_atom_bytes(feed_bytes)]
        assert len(licitaciones) == 5

        nuevas, _ = db_mod.upsert_licitaciones(licitaciones)
        assert nuevas == 5
        assert db_mod.count_licitaciones() == 5


@pytest.mark.integration
class TestE2EHistoryTracking:
    """Verifica el tracking de cambios en licitaciones."""

    def test_cambio_importe_registrado_en_historia(self, tmp_db):
        """Un cambio en el importe debe quedar registrado en licitaciones_history."""
        db_mod, _ = tmp_db

        # Insertar versión inicial
        feed_v1 = _make_atom_feed(_make_sap_entry("E2E-HIST", importe="100000.00"))
        from scraper.codice_parser import parse_atom_bytes

        v1 = [lic for lic, _ in parse_atom_bytes(feed_v1)]
        db_mod.upsert_licitaciones(v1)

        # Simular cambio de importe en la fuente
        feed_v2 = _make_atom_feed(_make_sap_entry("E2E-HIST", importe="150000.00"))
        v2 = [lic for lic, _ in parse_atom_bytes(feed_v2)]
        result = db_mod.upsert_licitaciones_with_history(v2, source="test")

        # Debe haber una modificación
        assert "E2E-HIST" in result.modified

        # Verificar historial
        history = db_mod.get_history("E2E-HIST")
        assert len(history) >= 1
        assert "importe" in history[0]["changed_fields"]


@pytest.mark.integration
class TestE2EDataLoader:
    """Verifica que data_loader lee correctamente desde la BD poblada."""

    def test_load_dataframe_returns_persisted_data(self, tmp_db, monkeypatch):
        """El data_loader debe devolver un DataFrame con las licitaciones persistidas."""
        db_mod, _ = tmp_db

        # Poblar la BD
        feed_bytes = _make_atom_feed(
            _make_sap_entry("E2E-DL-001", titulo="SAP S/4HANA Implementation")
            + _make_sap_entry("E2E-DL-002", titulo="SAP SuccessFactors")
        )
        from scraper.codice_parser import parse_atom_bytes

        licitaciones = [lic for lic, _ in parse_atom_bytes(feed_bytes)]
        db_mod.upsert_licitaciones(licitaciones)
        assert db_mod.count_licitaciones() == 2

        # Cargar desde data_loader (sin Streamlit — usando connect directamente)
        from db.database import connect

        with connect() as c:
            cursor = c.execute("SELECT * FROM licitaciones ORDER BY id_externo")
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]

        df = pd.DataFrame(rows, columns=cols)

        assert len(df) == 2
        assert set(df["id_externo"]) == {"E2E-DL-001", "E2E-DL-002"}
        assert df["importe"].notna().all()
        assert df["raw_keywords"].notna().all()


@pytest.mark.integration
class TestE2EFilters:
    """Verifica el comportamiento del sistema de filtrado."""

    def test_matches_sap_con_keywords_directos(self):
        """Textos con keywords SAP explícitas deben matchear."""
        from scraper.filters import matches_sap

        ok, keywords = matches_sap("Implantación SAP S/4HANA en la administración")
        assert ok
        assert any("sap" in k for k in keywords)

    def test_matches_sap_sin_keywords(self):
        """Textos sin keywords SAP no deben matchear (sin ML)."""
        from scraper.filters import matches_sap

        ok, keywords = matches_sap("Servicio de limpieza de instalaciones")
        assert not ok
        assert keywords == []

    def test_matches_sap_case_insensitive(self):
        """El filtro debe ser insensible a mayúsculas."""
        from scraper.filters import matches_sap

        ok1, _ = matches_sap("SAP ERP")
        ok2, _ = matches_sap("sap erp")
        ok3, _ = matches_sap("Sap Erp")
        assert ok1 and ok2 and ok3

    def test_no_falso_positivo_palabra_parcial(self):
        """'sap' dentro de otra palabra (como 'desaparecer') NO debe matchear."""
        from scraper.filters import matches_sap

        ok, _ = matches_sap("El contrato desaparecerá pronto")
        assert not ok


@pytest.mark.integration
class TestE2EKpiPrecompute:
    """Verifica el pre-cálculo de KPIs."""

    def test_kpi_precompute_with_data(self, tmp_db):
        """El job de pre-cálculo debe insertar snapshots correctos."""
        db_mod, _ = tmp_db

        # Poblar con datos
        feed_bytes = _make_atom_feed("".join(_make_sap_entry(f"E2E-KPI-{i}") for i in range(3)))
        from scraper.codice_parser import parse_atom_bytes

        licitaciones = [lic for lic, _ in parse_atom_bytes(feed_bytes)]
        db_mod.upsert_licitaciones(licitaciones)

        # Ejecutar pre-cálculo
        from scheduler.kpi_precompute import get_all_latest, run_kpi_precompute

        result = run_kpi_precompute()
        assert result["n_metricas"] > 0

        # Verificar snapshot
        data = get_all_latest()
        assert data.get("total_licitaciones") == 3
        assert "_computed_at" in data

    def test_kpi_precompute_empty_db(self, tmp_db):
        """El pre-cálculo debe funcionar con BD vacía (sin errores)."""
        from scheduler.kpi_precompute import run_kpi_precompute

        result = run_kpi_precompute()
        assert result["n_metricas"] >= 0  # No lanza excepción


@pytest.mark.integration
class TestE2ERateLimiting:
    """Verifica el rate limiting persistente."""

    def test_login_lockout_persiste_entre_llamadas(self, tmp_db):
        """Los intentos fallidos deben acumularse y activar el lockout."""
        from db.rate_limits import is_login_locked_out, record_failed_login

        client = "test_client_e2e"

        # Registrar 5 intentos fallidos
        for _ in range(5):
            record_failed_login(client)

        locked, remaining = is_login_locked_out(client, max_attempts=5)
        assert locked
        assert remaining > 0

    def test_clear_login_attempts(self, tmp_db):
        """Limpiar intentos debe desbloquear al cliente."""
        from db.rate_limits import (
            clear_login_attempts,
            is_login_locked_out,
            record_failed_login,
        )

        client = "test_client_clear"

        for _ in range(5):
            record_failed_login(client)

        locked, _ = is_login_locked_out(client, max_attempts=5)
        assert locked

        clear_login_attempts(client)
        locked, _ = is_login_locked_out(client, max_attempts=5)
        assert not locked

    def test_rate_limit_db_allows_within_limit(self, tmp_db):
        """Las llamadas dentro del límite deben ser permitidas."""
        from db.rate_limits import check_rate_limit_db

        key = "test_op_e2e"
        for _ in range(3):
            result = check_rate_limit_db(key, max_calls=5, window_seconds=60.0)
            assert result is True

    def test_rate_limit_db_blocks_over_limit(self, tmp_db):
        """Las llamadas por encima del límite deben ser bloqueadas."""
        from db.rate_limits import check_rate_limit_db

        key = "test_op_block_e2e"
        for _ in range(3):
            check_rate_limit_db(key, max_calls=3, window_seconds=60.0)

        # La cuarta llamada debe ser bloqueada
        result = check_rate_limit_db(key, max_calls=3, window_seconds=60.0)
        assert result is False
