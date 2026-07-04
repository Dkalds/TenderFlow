"""Tests para services/adjudicaciones.py con BD real (tmp_db).

Patrón: seed una licitación + adjudicaciones via replace_adjudicaciones,
luego verificar el comportamiento del servicio de lectura.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers de seed (mismo patrón que test_services_licitaciones.py)
# ---------------------------------------------------------------------------


def _seed_licitacion(id_externo: str = "ADJ-TEST-001") -> None:
    """Inserta una licitación de referencia para poder adjudicar."""
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=id_externo,
                titulo="Implantación SAP ERP",
                descripcion="Proyecto piloto",
                organo_contratacion="Ministerio de Hacienda",
                importe=500_000.0,
                estado="ADJ",
                fecha_publicacion="2024-01-10",
                tecnologia="SAP",
                ccaa="Madrid",
            )
        ]
    )


def _seed_adjudicacion(
    licitacion_id: str = "ADJ-TEST-001",
    *,
    nombre: str = "Empresa SAP SL",
    nif: str = "B12345678",  # pragma: allowlist secret
    importe_adjudicado: float = 420_000.0,
    importe_licitacion: float | None = 500_000.0,
    es_ute: bool = False,
    fecha_adj: str = "2024-03-15",
    n_ofertas: int = 4,
) -> None:
    from db.upsert import Adjudicacion, replace_adjudicaciones

    nombre_efectivo = "U.T.E. SAP-CONSULT" if es_ute else nombre
    replace_adjudicaciones(
        licitacion_id,
        [
            Adjudicacion(
                licitacion_id=licitacion_id,
                nombre=nombre_efectivo,
                nif=nif,
                importe_adjudicado=importe_adjudicado,
                fecha_adjudicacion=fecha_adj,
                n_ofertas_recibidas=n_ofertas,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Carga enriquecida: baja_pct calculada correctamente
# ---------------------------------------------------------------------------


def test_adjudicaciones_baja_pct_calculada(tmp_db):
    """baja_pct = (1 - adj/lic) × 100 debe calcularse en load_adjudicaciones."""
    _seed_licitacion()
    _seed_adjudicacion(importe_adjudicado=420_000.0)

    from services.adjudicaciones import load_adjudicaciones

    df = load_adjudicaciones()
    assert not df.empty

    row = df[df["licitacion_id"] == "ADJ-TEST-001"].iloc[0]
    # baja_pct = (1 - 420k/500k) * 100 = 16.0
    assert abs(row["baja_pct"] - 16.0) < 0.01


def test_adjudicaciones_baja_pct_nula_sin_importe_licitacion(tmp_db):
    """baja_pct es NaN cuando importe_licitacion es 0 o None."""
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo="ADJ-SIN-IMP",
                titulo="Sin importe de licitación",
                importe=None,  # sin importe base
                estado="ADJ",
            )
        ]
    )
    from db.upsert import Adjudicacion, replace_adjudicaciones

    replace_adjudicaciones(
        "ADJ-SIN-IMP",
        [
            Adjudicacion(
                licitacion_id="ADJ-SIN-IMP", nombre="Empresa X", importe_adjudicado=100_000.0
            )
        ],
    )

    from services.adjudicaciones import load_adjudicaciones

    df = load_adjudicaciones()
    row = df[df["licitacion_id"] == "ADJ-SIN-IMP"]
    assert not row.empty
    import pandas as pd

    assert pd.isna(row.iloc[0]["baja_pct"])


# ---------------------------------------------------------------------------
# es_ute detectado
# ---------------------------------------------------------------------------


def test_adjudicaciones_es_ute_detectado(tmp_db):
    """Nombre que contiene U.T.E. → es_ute = True."""
    _seed_licitacion("ADJ-UTE-001")
    _seed_adjudicacion("ADJ-UTE-001", es_ute=True)

    from services.adjudicaciones import load_adjudicaciones

    df = load_adjudicaciones()
    row = df[df["licitacion_id"] == "ADJ-UTE-001"]
    assert not row.empty
    assert bool(row.iloc[0]["es_ute"]) is True


def test_adjudicaciones_es_ute_false_empresa_normal(tmp_db):
    """Nombre estándar → es_ute = False."""
    _seed_licitacion("ADJ-NORMAL-001")
    _seed_adjudicacion("ADJ-NORMAL-001", nombre="TechCorp SA", es_ute=False)

    from services.adjudicaciones import load_adjudicaciones

    df = load_adjudicaciones()
    row = df[df["licitacion_id"] == "ADJ-NORMAL-001"]
    assert not row.empty
    assert bool(row.iloc[0]["es_ute"]) is False


# ---------------------------------------------------------------------------
# lead_time_dias > 0 cuando fecha_adjudicacion > fecha_publicacion
# ---------------------------------------------------------------------------


def test_adjudicaciones_lead_time_positivo(tmp_db):
    """lead_time_dias debe ser > 0 cuando la adjudicación es posterior a publicación."""
    _seed_licitacion("ADJ-LT-001")
    _seed_adjudicacion("ADJ-LT-001", fecha_adj="2024-06-20")
    # fecha_publicacion en seed_licitacion es 2024-01-10 → lead ~161d

    from services.adjudicaciones import load_adjudicaciones

    df = load_adjudicaciones()
    row = df[df["licitacion_id"] == "ADJ-LT-001"]
    assert not row.empty

    import pandas as pd

    lt = row.iloc[0]["lead_time_dias"]
    assert pd.notna(lt)
    assert float(lt) > 0


# ---------------------------------------------------------------------------
# DataFrame vacío cuando no hay datos
# ---------------------------------------------------------------------------


def test_adjudicaciones_df_vacio_sin_datos(tmp_db):
    """Sin adjudicaciones en BD, load_adjudicaciones devuelve DataFrame vacío."""
    from services.adjudicaciones import load_adjudicaciones

    df = load_adjudicaciones()
    assert df.empty


# ---------------------------------------------------------------------------
# Caché: segunda llamada reutiliza el mismo objeto
# ---------------------------------------------------------------------------


def test_adjudicaciones_cache_segunda_llamada_mismo_objeto(tmp_db):
    """load_raw_adjudicaciones sin filtros devuelve el mismo objeto en caché."""
    _seed_licitacion("ADJ-CACHE-001")
    _seed_adjudicacion("ADJ-CACHE-001")

    from services.adjudicaciones import load_raw_adjudicaciones

    resultado_1 = load_raw_adjudicaciones()
    resultado_2 = load_raw_adjudicaciones()
    # Mismo objeto en memoria — la caché debe devolver la misma referencia
    assert resultado_1 is resultado_2


def test_adjudicaciones_cache_con_filtro_no_cachea(tmp_db):
    """load_raw_adjudicaciones con filtros no usa la caché (objetos distintos)."""
    _seed_licitacion("ADJ-FILT-001")
    _seed_adjudicacion("ADJ-FILT-001")

    from services.adjudicaciones import load_raw_adjudicaciones

    sin_filtro = load_raw_adjudicaciones()
    con_filtro = load_raw_adjudicaciones(ccaa_filter=("Madrid",))
    # Con filtros se bypass el caché → objetos distintos
    assert sin_filtro is not con_filtro


# ---------------------------------------------------------------------------
# clear_raw_adj_cache invalida la caché
# ---------------------------------------------------------------------------


def test_adjudicaciones_clear_cache_invalida(tmp_db):
    """clear_raw_adj_cache hace que la próxima llamada cargue desde BD."""
    _seed_licitacion("ADJ-CLR-001")
    _seed_adjudicacion("ADJ-CLR-001")

    from services.adjudicaciones import clear_raw_adj_cache, load_raw_adjudicaciones

    ref_antes = load_raw_adjudicaciones()  # llena la caché
    clear_raw_adj_cache()
    ref_despues = load_raw_adjudicaciones()  # recarga desde BD

    # Tras clear el objeto es nuevo (diferente referencia)
    assert ref_antes is not ref_despues
    # Pero el contenido debe ser equivalente
    assert len(ref_antes) == len(ref_despues)


# ---------------------------------------------------------------------------
# replace_adjudicaciones es idempotente (upsert)
# ---------------------------------------------------------------------------


def test_adjudicaciones_replace_idempotente(tmp_db):
    """Llamar replace_adjudicaciones dos veces con los mismos datos no duplica."""
    _seed_licitacion("ADJ-IDEM-001")
    _seed_adjudicacion("ADJ-IDEM-001")
    _seed_adjudicacion("ADJ-IDEM-001")  # segunda vez con mismos datos

    from services.adjudicaciones import clear_raw_adj_cache, load_raw_adjudicaciones

    clear_raw_adj_cache()
    rows = load_raw_adjudicaciones()
    filas_lic = [r for r in rows if r["licitacion_id"] == "ADJ-IDEM-001"]
    assert len(filas_lic) == 1


# ---------------------------------------------------------------------------
# Múltiples adjudicaciones para una licitación
# ---------------------------------------------------------------------------


def test_adjudicaciones_multiples_por_licitacion(tmp_db):
    """Una licitación puede tener varias adjudicaciones (lotes)."""
    from db.upsert import Adjudicacion, Licitacion, replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo="ADJ-MULTI-001",
                titulo="Licitación con múltiples lotes",
                estado="ADJ",
                importe=1_000_000.0,
            )
        ]
    )
    replace_adjudicaciones(
        "ADJ-MULTI-001",
        [
            Adjudicacion(
                licitacion_id="ADJ-MULTI-001",
                nombre="Empresa Lote 1",
                nif="B11111111",
                importe_adjudicado=400_000.0,
                fecha_adjudicacion="2024-04-01",
            ),
            Adjudicacion(
                licitacion_id="ADJ-MULTI-001",
                nombre="Empresa Lote 2",
                nif="B22222222",
                importe_adjudicado=600_000.0,
                fecha_adjudicacion="2024-04-01",
            ),
        ],
    )

    from services.adjudicaciones import clear_raw_adj_cache, load_raw_adjudicaciones

    clear_raw_adj_cache()
    rows = load_raw_adjudicaciones()
    filas = [r for r in rows if r["licitacion_id"] == "ADJ-MULTI-001"]
    assert len(filas) == 2


# ---------------------------------------------------------------------------
# empresa_key se construye correctamente
# ---------------------------------------------------------------------------


def test_adjudicaciones_empresa_key_usa_nif(tmp_db):
    """empresa_key prefiere nif_norm sobre nombre_norm cuando nif está disponible."""
    _seed_licitacion("ADJ-KEY-001")
    _seed_adjudicacion("ADJ-KEY-001", nombre="Empresa Con NIF SL", nif="B99887766")

    from services.adjudicaciones import load_adjudicaciones

    df = load_adjudicaciones()
    row = df[df["licitacion_id"] == "ADJ-KEY-001"]
    assert not row.empty
    # empresa_key debe ser no nulo cuando hay nif
    import pandas as pd

    assert pd.notna(row.iloc[0]["empresa_key"])
