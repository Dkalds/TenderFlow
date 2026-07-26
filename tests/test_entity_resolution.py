"""Tests para el maestro de empresas (db/empresas.py + services/entity_resolution.py)."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    """Devuelve el módulo db tras inicializar la BD."""
    db_mod, _ = tmp_db
    return db_mod


def make_licitacion(id_externo="LIC-001", **kwargs):
    from db.upsert import Licitacion

    defaults = {
        "id_externo": id_externo,
        "titulo": "Implantación SAP",
        "fecha_publicacion": "2024-01-15",
    }
    defaults.update(kwargs)
    return Licitacion(**defaults)


def insert_adj(db, nombre, nif=None, lic_id="LIC-001", importe=100000.0):
    """Inserta una adjudicación directa (sin pasar por el parser)."""
    from db.upsert import Adjudicacion, replace_adjudicaciones_batch

    adj = Adjudicacion(licitacion_id=lic_id, nombre=nombre, nif=nif, importe_adjudicado=importe)
    total, _dropped, failed = replace_adjudicaciones_batch({lic_id: [adj]})
    assert failed == 0
    return total


def setup_lic(db, lic_id="LIC-001"):
    from db.upsert import upsert_licitaciones

    upsert_licitaciones([make_licitacion(lic_id)])


# ---------------------------------------------------------------------------
# Migración v35 — schema
# ---------------------------------------------------------------------------


def test_v35_tables_exist(db):
    from db.database import connect, is_postgres_backend

    # sqlite_master no existe en Postgres; information_schema no existe en
    # SQLite. Se consulta el catálogo de cada motor (ADR-018).
    if is_postgres_backend():
        sql = (
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
        )
    else:
        sql = "SELECT name FROM sqlite_master WHERE type='table'"

    with connect() as c:
        tables = {r[0] for r in c.execute(sql).fetchall()}
    assert {
        "empresas",
        "empresa_aliases",
        "grupos_empresariales",
        "ute_miembros",
        "empresa_review_queue",
    } <= tables


def test_v35_adjudicaciones_has_empresa_id(db):
    from db.database import connect, get_table_columns

    with connect() as c:
        cols = set(get_table_columns(c, "adjudicaciones"))
    assert "empresa_id" in cols


# ---------------------------------------------------------------------------
# Cadena de resolución
# ---------------------------------------------------------------------------


def test_new_company_created_and_linked(db):
    from services.entity_resolution import resolve_unlinked_adjudicaciones

    setup_lic(db)
    insert_adj(db, "ACME Consulting S.L.", nif="B12345678")
    stats = resolve_unlinked_adjudicaciones()

    assert stats.created == 1
    from db.database import connect

    with connect() as c:
        nif, nombre = c.execute(
            "SELECT e.nif_canonico, e.nombre_canonico FROM adjudicaciones a "
            "JOIN empresas e ON e.empresa_id = a.empresa_id"
        ).fetchone()
    assert nif == "B12345678"
    assert nombre == "ACME Consulting S.L."


def test_nif_match_links_to_existing(db):
    """Variantes del mismo NIF se agrupan en una sola empresa."""
    from services.entity_resolution import resolve_unlinked_adjudicaciones

    setup_lic(db, "LIC-001")
    setup_lic(db, "LIC-002")
    insert_adj(db, "ACME Consulting S.L.", nif="B12345678", lic_id="LIC-001")
    insert_adj(db, "ACME CONSULTING SLU", nif="b-12345678", lic_id="LIC-002")
    stats = resolve_unlinked_adjudicaciones()

    assert stats.created == 1
    assert stats.linked_nif == 1
    from db.database import connect

    with connect() as c:
        n_empresas = c.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
        n_distinct = c.execute("SELECT COUNT(DISTINCT empresa_id) FROM adjudicaciones").fetchone()[
            0
        ]
    assert n_empresas == 1
    assert n_distinct == 1


def test_alias_match_without_nif(db):
    """Mismo nombre normalizado sin NIF enlaza con la empresa existente."""
    from services.entity_resolution import resolve_unlinked_adjudicaciones

    setup_lic(db, "LIC-001")
    setup_lic(db, "LIC-002")
    insert_adj(db, "Indra Sistemas S.A.", nif="A28599033", lic_id="LIC-001")
    insert_adj(db, "INDRA SISTEMAS, S.A.", nif=None, lic_id="LIC-002")
    stats = resolve_unlinked_adjudicaciones()

    assert stats.created == 1
    assert stats.linked_alias == 1


def test_alias_match_adds_missing_canonical_nif(db):
    """Un alias conocido completa el NIF canónico cuando llega posteriormente."""
    from db.database import connect
    from services.entity_resolution import resolve_unlinked_adjudicaciones

    setup_lic(db, "LIC-001")
    setup_lic(db, "LIC-002")
    insert_adj(db, "Deloitte Consulting S.L.U.", lic_id="LIC-001")
    resolve_unlinked_adjudicaciones()
    insert_adj(db, "DELOITTE CONSULTING SLU", nif="B81690471", lic_id="LIC-002")

    stats = resolve_unlinked_adjudicaciones()

    assert stats.linked_alias == 1
    with connect() as c:
        assert c.execute("SELECT nif_canonico FROM empresas").fetchone()[0] == "B81690471"


def test_nif_match_links_when_name_normalizes_to_empty(db):
    """Un NIF exacto prevalece aunque el nombre recibido sea solo forma jurídica."""
    from db.database import connect
    from services.entity_resolution import resolve_unlinked_adjudicaciones

    setup_lic(db, "LIC-001")
    setup_lic(db, "LIC-002")
    insert_adj(db, "Bluetab Solutions SLU", nif="B84521269", lic_id="LIC-001")
    resolve_unlinked_adjudicaciones()
    insert_adj(db, "S.L.U.", nif="B84521269", lic_id="LIC-002")

    stats = resolve_unlinked_adjudicaciones()

    assert stats.linked_nif == 1
    with connect() as c:
        assert c.execute("SELECT COUNT(DISTINCT empresa_id) FROM adjudicaciones").fetchone()[0] == 1


def test_nif_conflict_goes_to_review(db):
    """Mismo nombre normalizado con NIF distinto no se enlaza: cola de revisión."""
    from services.entity_resolution import resolve_unlinked_adjudicaciones

    setup_lic(db, "LIC-001")
    setup_lic(db, "LIC-002")
    insert_adj(db, "Accenture S.L.", nif="B11111111", lic_id="LIC-001")
    insert_adj(db, "ACCENTURE SA", nif="A22222222", lic_id="LIC-002")
    stats = resolve_unlinked_adjudicaciones()

    assert stats.created == 1
    assert stats.queued_review == 1
    from db.database import connect

    with connect() as c:
        unlinked = c.execute(
            "SELECT COUNT(*) FROM adjudicaciones WHERE empresa_id IS NULL"
        ).fetchone()[0]
    assert unlinked == 1


def test_fuzzy_near_match_goes_to_review(db):
    """Nombre casi idéntico (typo) va a revisión, nunca enlace automático."""
    from services.entity_resolution import resolve_unlinked_adjudicaciones

    setup_lic(db, "LIC-001")
    setup_lic(db, "LIC-002")
    insert_adj(db, "Telefonica Soluciones de Informatica SA", lic_id="LIC-001")
    insert_adj(db, "Telefonica Soluciones de Informatic SA", lic_id="LIC-002")
    stats = resolve_unlinked_adjudicaciones()

    assert stats.created == 1
    assert stats.queued_review == 1


def test_distinct_companies_not_merged(db):
    """Nombres claramente distintos crean empresas separadas."""
    from services.entity_resolution import resolve_unlinked_adjudicaciones

    setup_lic(db, "LIC-001")
    setup_lic(db, "LIC-002")
    insert_adj(db, "Everis Spain S.L.", lic_id="LIC-001")
    insert_adj(db, "Capgemini España S.L.", lic_id="LIC-002")
    stats = resolve_unlinked_adjudicaciones()

    assert stats.created == 2
    assert stats.queued_review == 0


def test_ute_creates_members(db):
    from services.entity_resolution import resolve_unlinked_adjudicaciones

    setup_lic(db)
    insert_adj(db, "UTE INDRA SISTEMAS - MINSAIT")
    stats = resolve_unlinked_adjudicaciones()

    assert stats.utes == 1
    from db.database import connect

    with connect() as c:
        es_ute = c.execute(
            "SELECT e.es_ute FROM adjudicaciones a JOIN empresas e ON e.empresa_id = a.empresa_id"
        ).fetchone()[0]
        n_members = c.execute("SELECT COUNT(*) FROM ute_miembros").fetchone()[0]
    assert es_ute == 1
    assert n_members == 2


def test_resolution_idempotent(db):
    """Segunda pasada no crea duplicados ni reprocesa filas enlazadas."""
    from services.entity_resolution import resolve_unlinked_adjudicaciones

    setup_lic(db)
    insert_adj(db, "ACME Consulting S.L.", nif="B12345678")
    resolve_unlinked_adjudicaciones()
    stats2 = resolve_unlinked_adjudicaciones()

    assert stats2.fetched == 0
    from db.database import connect

    with connect() as c:
        assert c.execute("SELECT COUNT(*) FROM empresas").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Cola de revisión — apply_review
# ---------------------------------------------------------------------------


def _make_review(db):
    """Genera una entrada de revisión real vía conflicto de NIF."""
    from db.database import connect
    from services.entity_resolution import resolve_unlinked_adjudicaciones

    setup_lic(db, "LIC-001")
    setup_lic(db, "LIC-002")
    insert_adj(db, "Accenture S.L.", nif="B11111111", lic_id="LIC-001")
    insert_adj(db, "ACCENTURE SA", nif="A22222222", lic_id="LIC-002")
    resolve_unlinked_adjudicaciones()
    with connect() as c:
        review_id, candidato = c.execute(
            "SELECT id, candidato_empresa_id FROM empresa_review_queue WHERE status='pending'"
        ).fetchone()
    return int(review_id), int(candidato)


def test_apply_review_accept_links_to_candidate(db):
    from db.database import connect
    from db.empresas import apply_review

    review_id, candidato = _make_review(db)
    empresa_id = apply_review(review_id, accept=True, resolved_by="test")

    assert empresa_id == candidato
    with connect() as c:
        unlinked = c.execute(
            "SELECT COUNT(*) FROM adjudicaciones WHERE empresa_id IS NULL"
        ).fetchone()[0]
        status_ = c.execute(
            "SELECT status FROM empresa_review_queue WHERE id = ?", (review_id,)
        ).fetchone()[0]
    assert unlinked == 0
    assert status_ == "accepted"


def test_apply_review_reject_creates_new_company(db):
    from db.database import connect
    from db.empresas import apply_review

    review_id, candidato = _make_review(db)
    empresa_id = apply_review(review_id, accept=False, resolved_by="test")

    assert empresa_id != candidato
    with connect() as c:
        n_empresas = c.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
        unlinked = c.execute(
            "SELECT COUNT(*) FROM adjudicaciones WHERE empresa_id IS NULL"
        ).fetchone()[0]
    assert n_empresas == 2
    assert unlinked == 0


def test_apply_review_missing_returns_none(db):
    from db.empresas import apply_review

    assert apply_review(99999, accept=True) is None


# ---------------------------------------------------------------------------
# Backfill completo + stats
# ---------------------------------------------------------------------------


def test_resolve_all_unlinked_drains_everything(db):
    from db.empresas import resolution_stats
    from services.entity_resolution import resolve_all_unlinked

    # Nombres claramente distintos: variar solo un dígito los haría caer
    # (correctamente) en la cola de revisión fuzzy.
    nombres = [
        "Aguas del Norte S.A.",
        "Construcciones Velez S.L.",
        "Informatica El Corte Ingles",
        "Viewnext S.A.",
        "Babel Sistemas de Informacion",
        "Seidor Consulting",
        "Sopra Steria España",
    ]
    for i, nombre in enumerate(nombres, start=1):
        setup_lic(db, f"LIC-{i:03d}")
        insert_adj(db, nombre, nif=f"B0000000{i}", lic_id=f"LIC-{i:03d}")

    total = resolve_all_unlinked(batch_size=3)
    assert total.created == 7

    stats = resolution_stats()
    assert stats["adjudicaciones_enlazadas"] == 7
    assert stats["pct_filas"] == 100.0
    assert stats["empresas"] == 7


def test_resolution_stats_empty_db(db):
    from db.empresas import resolution_stats

    stats = resolution_stats()
    assert stats["adjudicaciones_total"] == 0
    assert stats["pct_filas"] == 0.0
