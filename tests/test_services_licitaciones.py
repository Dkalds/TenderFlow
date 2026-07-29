"""Tests para services/licitaciones.py — list, search, load funciones."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def seed_licitaciones(db_mod, n=5):
    """Inserta N licitaciones de prueba en la BD."""
    from db.upsert import Licitacion, upsert_licitaciones

    lics = []
    for i in range(n):
        lics.append(
            Licitacion(
                id_externo=f"SVC-{i:03d}",
                titulo=f"Sistema SAP módulo {i}",
                descripcion=f"Implantación de SAP ERP versión {i}",
                organo_contratacion=f"Ministerio {i}",
                importe=float(100_000 * (i + 1)),
                estado="PUB",
                fecha_publicacion=f"2024-0{(i % 9) + 1}-15",
                tecnologia="SAP",
                ccaa=["Madrid", "Cataluña", "Andalucía", "Galicia", "Valencia"][i % 5],
            )
        )
    upsert_licitaciones(lics)
    return lics


# ---------------------------------------------------------------------------
# list_licitaciones
# ---------------------------------------------------------------------------


def test_list_licitaciones_returns_items(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from services.licitaciones import list_licitaciones

    items, total = list_licitaciones()
    assert total >= 3
    assert len(items) >= 3


def test_list_licitaciones_pagination(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 10)

    from services.licitaciones import list_licitaciones

    items, total = list_licitaciones(limit=3, offset=0)
    assert len(items) == 3
    assert total >= 10

    items2, _ = list_licitaciones(limit=3, offset=3)
    ids1 = {i["id_externo"] for i in items}
    ids2 = {i["id_externo"] for i in items2}
    assert ids1.isdisjoint(ids2)


def test_list_licitaciones_filter_ccaa(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 10)

    from services.licitaciones import list_licitaciones

    items, _total = list_licitaciones(ccaa="Madrid")
    for item in items:
        assert item["ccaa"] == "Madrid"


def test_list_licitaciones_filter_estado(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 5)

    from services.licitaciones import list_licitaciones

    items, _total = list_licitaciones(estado="PUB")
    for item in items:
        assert item["estado"] == "PUB"


def test_list_licitaciones_filter_tecnologia(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 5)

    from services.licitaciones import list_licitaciones

    items, _total = list_licitaciones(tecnologia="SAP")
    for item in items:
        assert item["tecnologia"] == "SAP"


def test_list_licitaciones_text_search(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 5)

    from services.licitaciones import list_licitaciones

    _items, total = list_licitaciones(q="SAP")
    assert total >= 1


def test_list_licitaciones_empty_db(tmp_db):
    from services.licitaciones import list_licitaciones

    items, total = list_licitaciones()
    assert isinstance(items, list)
    assert isinstance(total, int)


# ---------------------------------------------------------------------------
# get_licitacion_detail
# ---------------------------------------------------------------------------


def test_get_licitacion_detail_found(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 1)

    from services.licitaciones import get_licitacion_detail

    detail = get_licitacion_detail("SVC-000")
    assert detail is not None
    assert detail["id_externo"] == "SVC-000"


def test_get_licitacion_detail_not_found(tmp_db):
    from services.licitaciones import get_licitacion_detail

    detail = get_licitacion_detail("NONEXISTENT-XYZ")
    assert detail is None


# ---------------------------------------------------------------------------
# load_raw
# ---------------------------------------------------------------------------


def test_load_raw_returns_list(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from services.licitaciones import load_raw

    rows = load_raw()
    assert isinstance(rows, list)
    assert len(rows) >= 3


def test_load_raw_with_limit(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 10)

    from services.licitaciones import load_raw

    rows = load_raw(limit=2)
    assert len(rows) == 2


def test_load_raw_fields(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 1)

    from services.licitaciones import load_raw

    rows = load_raw()
    row = rows[0]
    assert "id_externo" in row
    assert "titulo" in row
    assert "tecnologia" in row


# ---------------------------------------------------------------------------
# load_stats_dataframe
# ---------------------------------------------------------------------------


def test_load_stats_dataframe_returns_list(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from services.licitaciones import load_stats_dataframe

    rows = load_stats_dataframe()
    assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# load_stats_base_df — caché compartida (sin .copy() desde wave 2/A3)
# ---------------------------------------------------------------------------


def test_load_stats_base_df_applies_canonical_conversions(tmp_db):
    """fecha_publicacion/importe llegan ya convertidos, no como string/objeto crudo."""
    import pandas as pd

    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from services.licitaciones import clear_stats_cache, load_stats_base_df

    clear_stats_cache()
    df = load_stats_base_df()

    assert pd.api.types.is_datetime64_any_dtype(df["fecha_publicacion"])
    assert pd.api.types.is_numeric_dtype(df["importe"])


def test_load_stats_base_df_returns_shared_instance_across_calls(tmp_db):
    """Dos llamadas dentro de la ventana de caché devuelven el MISMO objeto
    Python (no dos copias) — es la propiedad que A3 explota para eliminar el
    .copy() por request."""
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from services.licitaciones import clear_stats_cache, load_stats_base_df

    clear_stats_cache()
    first = load_stats_base_df()
    second = load_stats_base_df()

    assert first is second


def test_load_stats_base_df_survives_concurrent_consumer_mutations(tmp_db):
    """Ejercita los consumidores reales que añaden columnas derivadas
    (resumen/pipeline/scoring/forecast_svc) y confirma que ninguno contamina
    la caché compartida para el siguiente consumidor.

    Antes de A3, esto no habría hecho falta (cada llamada recibía su propia
    copia). Con la caché compartida, un `df["col"] = valor` in-place en
    cualquiera de estos módulos correspondería a un consumidor mutando la
    instancia que ven todos los demás — este test falla si eso ocurre.
    """
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 5)

    from services.analytics.forecast_svc import _load_licit_df
    from services.analytics.pipeline import _load_df as _pipeline_load_df
    from services.analytics.resumen import _load_df as _resumen_load_df
    from services.analytics.scoring import ScoringFilters, get_scoring
    from services.licitaciones import clear_stats_cache, load_stats_base_df

    clear_stats_cache()

    baseline = load_stats_base_df()
    baseline_columns = set(baseline.columns)

    # Ejercita cada consumidor que históricamente mutaba in-place.
    _resumen_load_df()
    _pipeline_load_df()
    _load_licit_df()
    get_scoring(ScoringFilters())

    after = load_stats_base_df()
    assert after is baseline, "load_stats_base_df ya no devuelve la instancia compartida"
    assert set(after.columns) == baseline_columns, (
        "Un consumidor añadió columnas derivadas (fecha_limite_dt, duracion_valor, "
        "tipo_proyecto...) a la instancia compartida en vez de a una copia local"
    )


# ---------------------------------------------------------------------------
# load_uncertainty_zone
# ---------------------------------------------------------------------------


def test_load_uncertainty_zone_empty(tmp_db):
    from services.licitaciones import load_uncertainty_zone

    rows = load_uncertainty_zone(lo=0.3, hi=0.7, limit=50)
    assert isinstance(rows, list)


def test_load_uncertainty_zone_with_data(tmp_db):
    from db.upsert import Licitacion, upsert_licitaciones
    from services.licitaciones import load_uncertainty_zone

    lic = Licitacion(
        id_externo="UNC-001",
        titulo="Uncertain SAP project",
        tecnologia="SAP",
        ml_proba=0.5,
    )
    upsert_licitaciones([lic])

    rows = load_uncertainty_zone(lo=0.3, hi=0.7, limit=10)
    ids = [r["id_externo"] for r in rows]
    assert "UNC-001" in ids


# ---------------------------------------------------------------------------
# search_advanced
# ---------------------------------------------------------------------------


def test_search_advanced_no_filters(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 5)

    from services.licitaciones import search_advanced

    _items, total = search_advanced()
    assert total >= 5


def test_search_advanced_importe_range(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 5)

    from services.licitaciones import search_advanced

    items, _total = search_advanced(importe_min=100_000, importe_max=300_000)
    for item in items:
        assert item["importe"] >= 100_000
        assert item["importe"] <= 300_000


def test_search_advanced_multi_ccaa(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 10)

    from services.licitaciones import search_advanced

    items, _total = search_advanced(ccaa=["Madrid", "Cataluña"])
    for item in items:
        assert item["ccaa"] in ("Madrid", "Cataluña")


def test_search_advanced_fecha_range(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 5)

    from services.licitaciones import search_advanced

    _items, total = search_advanced(fecha_desde="2024-01-01", fecha_hasta="2024-12-31")
    assert isinstance(total, int)


def test_search_advanced_without_total(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from services.licitaciones import search_advanced

    _items, total = search_advanced(with_total=False)
    assert total == -1


# ---------------------------------------------------------------------------
# load_drift_window
# ---------------------------------------------------------------------------


def test_load_drift_window(tmp_db):
    db_mod, _ = tmp_db
    seed_licitaciones(db_mod, 3)

    from services.licitaciones import load_drift_window

    rows = load_drift_window(days=30)
    assert isinstance(rows, list)
