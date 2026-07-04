"""Tests para db/repositories/licitaciones.py — métodos no cubiertos en coverage."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def seed_licitaciones(db_mod, n: int = 5):
    """Inserta N licitaciones de prueba con tecnologia=SAP."""
    from db.upsert import Licitacion, upsert_licitaciones

    items = [
        Licitacion(
            id_externo=f"L{i:03d}",
            titulo=f"Licitacion {i} SAP FI CO mantenimiento",
            descripcion=f"Proyecto SAP FI modulo {i} implantacion",
            organo_contratacion="Ministerio",
            estado="PUB",
            fecha_publicacion="2026-01-01T00:00:00+00:00",
            fecha_extraccion="2026-01-01",
            tecnologia="SAP",
            cpv="72000000",
            ccaa="Madrid",
        )
        for i in range(n)
    ]
    upsert_licitaciones(items)
    return items


# ---------------------------------------------------------------------------
# get_by_ids
# ---------------------------------------------------------------------------


def test_repo_get_by_ids_orden(tmp_db):
    """get_by_ids preserva el orden de entrada."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    results = repo.get_by_ids(["L002", "L000", "L001"])
    assert len(results) == 3
    assert [r["id_externo"] for r in results] == ["L002", "L000", "L001"]


def test_repo_get_by_ids_vacio(tmp_db):
    """get_by_ids con lista vacía devuelve []."""
    _, _ = tmp_db

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    results = repo.get_by_ids([])
    assert results == []


def test_repo_get_by_ids_no_existe(tmp_db):
    """get_by_ids con id inexistente devuelve []."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 2)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    results = repo.get_by_ids(["NOPE"])
    assert results == []


# ---------------------------------------------------------------------------
# get_text_for_ml
# ---------------------------------------------------------------------------


def test_repo_get_text_for_ml_encontrado(tmp_db):
    """get_text_for_ml devuelve (titulo, descripcion, tecnologia) para id existente."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 1)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    result = repo.get_text_for_ml("L000")
    assert result is not None
    titulo, desc, tech = result
    assert "SAP" in titulo
    assert isinstance(desc, str)
    assert tech == "SAP"


def test_repo_get_text_for_ml_no_existe(tmp_db):
    """get_text_for_ml devuelve None para id inexistente."""
    _, _ = tmp_db

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    result = repo.get_text_for_ml("NOPE")
    assert result is None


# ---------------------------------------------------------------------------
# list_cursor
# ---------------------------------------------------------------------------


def test_repo_list_cursor_sin_cursor(tmp_db):
    """list_cursor sin cursor devuelve todas las licitaciones clasificadas."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 5)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    results = repo.list_cursor()
    assert len(results) >= 5
    for r in results:
        assert r["tecnologia"] is not None


def test_repo_list_cursor_filtro_tecnologia(tmp_db):
    """list_cursor con tecnologia filtra correctamente."""
    from db.upsert import Licitacion, upsert_licitaciones

    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)
    # Insertar una con tecnologia diferente
    upsert_licitaciones(
        [
            Licitacion(
                id_externo="OTRA-001",
                titulo="Otro ERP implantacion",
                tecnologia="Oracle",
                fecha_publicacion="2026-01-01T00:00:00+00:00",
                fecha_extraccion="2026-01-01",
            )
        ]
    )

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    results = repo.list_cursor(tecnologia="SAP")
    for r in results:
        assert r["tecnologia"] == "SAP"
    ids = {r["id_externo"] for r in results}
    assert "OTRA-001" not in ids


# ---------------------------------------------------------------------------
# search_fts_docs
# ---------------------------------------------------------------------------


def test_repo_search_fts_docs_devuelve_resultados(tmp_db):
    """search_fts_docs retorna documentos que contienen la query."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 5)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    results = repo.search_fts_docs("SAP FI mantenimiento")
    assert isinstance(results, list)
    # Con FTS disponible en tmp_db debe encontrar algo
    if results:
        assert "id_externo" in results[0]
        assert "titulo" in results[0]


def test_repo_search_fts_docs_sin_match(tmp_db):
    """search_fts_docs con query sin matches devuelve lista vacía."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    results = repo.search_fts_docs("XYZXYZXYZ123NUNCAEXISTE")
    assert isinstance(results, list)
    assert results == []


# ---------------------------------------------------------------------------
# search_like_for_ask
# ---------------------------------------------------------------------------


def test_repo_search_like_devuelve_resultados(tmp_db):
    """search_like_for_ask encuentra licitaciones que contienen las keywords."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 5)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    # "mantenimiento" es una palabra que aparece en todos los titulos sembrados
    results = repo.search_like_for_ask("mantenimiento SAP")
    assert isinstance(results, list)
    assert len(results) > 0
    for r in results:
        assert "id_externo" in r


def test_repo_search_like_vacio_sin_match(tmp_db):
    """search_like_for_ask sin matches devuelve lista vacía."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    results = repo.search_like_for_ask("XYZXYZ palabras inexistentes absolutamente")
    assert isinstance(results, list)
    assert results == []


# ---------------------------------------------------------------------------
# fts5_bm25_search
# ---------------------------------------------------------------------------


def test_repo_fts_bm25_devuelve_scores(tmp_db):
    """fts5_bm25_search retorna lista de (id, score) con scores en [0, 1]."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 5)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    results = repo.fts5_bm25_search("SAP FI mantenimiento", top_k=10)
    assert isinstance(results, list)
    if results:
        for id_ext, score in results:
            assert isinstance(id_ext, str)
            assert 0.0 <= score <= 1.0


def test_repo_fts_bm25_sin_match(tmp_db):
    """fts5_bm25_search con query sin matches devuelve []."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    results = repo.fts5_bm25_search("XYZXYZXYZ123NUNCAEXISTE", top_k=5)
    assert results == []


# ---------------------------------------------------------------------------
# fetch_metadata_by_ids
# ---------------------------------------------------------------------------


def test_repo_fetch_metadata_by_ids(tmp_db):
    """fetch_metadata_by_ids retorna dict con titulo para ids existentes."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    result = repo.fetch_metadata_by_ids(["L000"])
    assert isinstance(result, dict)
    assert "L000" in result
    assert "titulo" in result["L000"]
    assert "SAP" in result["L000"]["titulo"]


def test_repo_fetch_metadata_with_allowed_ids(tmp_db):
    """fetch_metadata_by_ids con allowed_ids solo devuelve ids permitidos."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    result = repo.fetch_metadata_by_ids(["L000", "L001"], allowed_ids={"L000"})
    assert "L000" in result
    assert "L001" not in result


def test_repo_fetch_metadata_ids_vacio(tmp_db):
    """fetch_metadata_by_ids con lista vacía devuelve {}."""
    _, _ = tmp_db

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    result = repo.fetch_metadata_by_ids([])
    assert result == {}


# ---------------------------------------------------------------------------
# get_last_extraction_date
# ---------------------------------------------------------------------------


def test_repo_get_last_extraction_date_vacio(tmp_db):
    """get_last_extraction_date sin datos devuelve None."""
    _, _ = tmp_db

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    result = repo.get_last_extraction_date()
    assert result is None


def test_repo_get_last_extraction_date_con_datos(tmp_db):
    """get_last_extraction_date con datos devuelve la fecha máxima como str."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    result = repo.get_last_extraction_date()
    assert result is not None
    assert isinstance(result, str)
    assert "2026-01-01" in result
