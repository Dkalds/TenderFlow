"""Tests del dedupe cross-fuente (Fase 5.2, RFC 20260611-1)."""

from __future__ import annotations

import pytest

from services.dedupe import (
    detect_duplicates,
    exclude_duplicados_sql,
    match_key,
    medir_solape,
    natural_expediente,
    normalize_organo,
    resolve_pending,
    review_pending,
)


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _insert_lic(c, id_externo, *, fuente, organo, cpv, fecha_pub, extraccion):
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, "
        " fecha_publicacion, fuente, fecha_extraccion) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id_externo, f"Contrato {id_externo}", organo, cpv, fecha_pub, fuente, extraccion),
    )


def _insert_adj(c, lic_id, nombre, importe):
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
        " fecha_adjudicacion, fecha_extraccion) VALUES (?, ?, ?, ?, datetime('now'))",
        (lic_id, nombre, importe, "2026-05-01"),
    )


# ---------------------------------------------------------------------------
# Helpers puros
# ---------------------------------------------------------------------------


def test_normalize_organo_pliega_acentos_y_formas():
    assert normalize_organo("Generalitat de Catalunya, S.A.") == "generalitat de catalunya"
    assert normalize_organo("GENERALITAT DE CATALUNYA") == "generalitat de catalunya"
    assert normalize_organo(None) is None


def test_natural_expediente_quita_namespace():
    assert natural_expediente("pscp:CTTI-2026-1") == "CTTI-2026-1"
    assert natural_expediente("EXP-PLACSP-7") == "EXP-PLACSP-7"  # placsp sin prefijo


def test_match_key():
    assert match_key("Òrgan A", "EXP-1", "72000000") == "organ a|EXP-1|7200"
    assert match_key("Òrgan A", "EXP-1", None) == "organ a|EXP-1|"
    assert match_key(None, "EXP-1", "72000000") is None


# ---------------------------------------------------------------------------
# Detección sobre par sintético PSCP↔PLACSP (acceptance del RFC)
# ---------------------------------------------------------------------------


def test_detect_marca_duplicado_exacto_y_excluye_en_analytics(db):
    from db.database import connect
    from services.competitive.mercado import cuota_mercado

    with connect() as c:
        _insert_lic(
            c, "EXP-2026-42", fuente="placsp", organo="Departament de Salut",
            cpv="72000000", fecha_pub="2026-05-01", extraccion="2026-05-02T00:00:00",
        )
        _insert_lic(
            c, "pscp:EXP-2026-42", fuente="pscp", organo="DEPARTAMENT DE SALUT",
            cpv="72004000", fecha_pub="2026-05-03", extraccion="2026-05-04T00:00:00",
        )
        _insert_adj(c, "EXP-2026-42", "Acme Consulting SL", 100000.0)
        _insert_adj(c, "pscp:EXP-2026-42", "Acme Consulting SL", 100000.0)

    result = detect_duplicates(fuente="pscp")

    assert result.evaluadas == 1
    assert result.confirmados == 1  # mismo órgano + expediente + CPV4 (7200)
    with connect() as c:
        row = c.execute(
            "SELECT canonical_id, confianza, status FROM licitaciones_duplicados "
            "WHERE licitacion_id = 'pscp:EXP-2026-42'"
        ).fetchone()
    assert row == ("EXP-2026-42", 1.0, "confirmed")  # canónico = PLACSP

    # Las métricas competitivas cuentan el contrato una sola vez
    cuota = cuota_mercado()
    acme = [r for r in cuota if r["empresa"] == "Acme Consulting SL"]
    assert acme and acme[0]["contratos"] == 1
    assert acme[0]["importe"] == 100000.0

    solape = medir_solape("pscp", "placsp")
    assert solape["solapadas"] == 1 and solape["solape_pct"] == 100.0


def test_detect_cpv_distinto_va_a_revision(db):
    from db.database import connect

    with connect() as c:
        _insert_lic(
            c, "EXP-9", fuente="placsp", organo="Ajuntament de Girona",
            cpv="48000000", fecha_pub="2026-05-01", extraccion="2026-05-02T00:00:00",
        )
        _insert_lic(
            c, "pscp:EXP-9", fuente="pscp", organo="Ajuntament de Girona",
            cpv="72000000", fecha_pub="2026-05-01", extraccion="2026-05-02T00:00:00",
        )

    result = detect_duplicates(fuente="pscp")

    assert result.pendientes == 1 and result.confirmados == 0
    pendientes = review_pending()
    assert len(pendientes) == 1
    assert pendientes[0]["confianza"] == 0.8

    # Pending NO se excluye de analytics hasta confirmación humana
    from db.database import connect_read

    with connect_read() as c:
        sql = f"SELECT COUNT(*) FROM licitaciones l WHERE {exclude_duplicados_sql()}"  # noqa: S608
        assert c.execute(sql).fetchone()[0] == 2

    assert resolve_pending("pscp:EXP-9", accept=True, resolved_by="test")
    with connect_read() as c:
        assert c.execute(sql).fetchone()[0] == 1
    assert review_pending() == []


def test_detect_es_incremental_por_cursor(db):
    from db.database import connect

    with connect() as c:
        _insert_lic(
            c, "EXP-1", fuente="placsp", organo="Organo X", cpv="72000000",
            fecha_pub="2026-05-01", extraccion="2026-05-02T00:00:00",
        )
        _insert_lic(
            c, "pscp:EXP-1", fuente="pscp", organo="Organo X", cpv="72000000",
            fecha_pub="2026-05-01", extraccion="2026-05-02T00:00:00",
        )

    first = detect_duplicates(fuente="pscp")
    second = detect_duplicates(fuente="pscp")

    assert first.evaluadas == 1 and first.confirmados == 1
    assert second.evaluadas == 0  # watermark avanzado: no re-evalúa


def test_detect_sin_match_no_marca(db):
    from db.database import connect

    with connect() as c:
        _insert_lic(
            c, "pscp:EXP-solo", fuente="pscp", organo="Organo Y", cpv="72000000",
            fecha_pub="2026-05-01", extraccion="2026-05-02T00:00:00",
        )

    result = detect_duplicates(fuente="pscp")

    assert result.evaluadas == 1
    assert result.confirmados == 0 and result.pendientes == 0
    with connect() as c:
        assert c.execute("SELECT COUNT(*) FROM licitaciones_duplicados").fetchone()[0] == 0
