"""El fallback pandas del export Parquet lee de Postgres de verdad.

Es el camino que corre en la imagen desplegada —``requirements.txt`` no trae
duckdb— y ningún test lo recorría: ``TestExportParquet`` sustituye el fallback
entero por un mock y ``tests/test_kpi_mat_queries.py`` ejecuta cada consulta
con su propio ``pd.read_sql``, sin pasar por
``db.kpi_precompute.mat_query_reader``. Un lector que no devolviese nada dejaba
el export vacío sin que fallase ningún test.

Los dos tests con Postgres solo sustituyen la escritura —``DataFrame.to_parquet``
necesita pyarrow, que no está en todos los entornos donde corre la suite— y, el
del job, ``has_duckdb`` para forzar el fallback. La conexión, el SQL y
``pd.read_sql`` son los reales. El tercero no va contra Postgres: sustituye
``connect`` por un adaptador sin conexión DBAPI cruda.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

from db.kpi_precompute import MAT_QUERIES

#: Lo que las cinco consultas tienen que devolver para ``_siembra``, por
#: columna clave → ``n``. Cubre todas las claves de ``MAT_QUERIES``: si se añade
#: una consulta sin su esperado, ``test_el_esperado_cubre_todas_las_consultas``
#: lo dice.
_ESPERADO: dict[str, tuple[str, dict[str, int]]] = {
    "mat_licitaciones_por_mes": ("mes", {"2026-03": 2, "2026-04": 1}),
    "mat_licitaciones_por_ccaa": ("ccaa", {"Madrid": 2, "Galicia": 1}),
    "mat_licitaciones_por_estado": ("estado", {"PUB": 2, "ADJ": 1}),
    "mat_top_adjudicatarios": ("nombre", {"Empresa A": 2, "Empresa B": 1}),
    "mat_licitaciones_por_tipo": ("tipo_contrato", {"Servicios": 2, "Suministros": 1}),
}


def _siembra(db_mod: Any) -> None:
    """Tres licitaciones del universo, cada una con una adjudicación con importe.

    Una cuarta, de ``watched_company_awards_observed`` y con su propia
    adjudicación, queda fuera del universo: no debe aparecer en ningún agregado.
    """
    from db.database import Adjudicacion, Licitacion

    db_mod.upsert_licitaciones(
        [
            Licitacion(
                id_externo="FB-1",
                titulo="SAP S/4HANA",
                fecha_publicacion="2026-03-14",
                ccaa="Madrid",
                estado="PUB",
                tipo_contrato="Servicios",
                importe=1000.0,
            ),
            Licitacion(
                id_externo="FB-2",
                titulo="SAP BW",
                fecha_publicacion="2026-03-28",
                ccaa="Madrid",
                estado="PUB",
                tipo_contrato="Servicios",
                importe=2000.0,
            ),
            Licitacion(
                id_externo="FB-3",
                titulo="Licencias SAP",
                fecha_publicacion="2026-04-02",
                ccaa="Galicia",
                estado="ADJ",
                tipo_contrato="Suministros",
                importe=500.0,
            ),
            Licitacion(
                id_externo="FB-FUERA",
                titulo="Solo empresa vigilada",
                fecha_publicacion="2026-04-10",
                ccaa="Galicia",
                estado="ADJ",
                tipo_contrato="Obras",
                importe=9000.0,
                analysis_universe="watched_company_awards_observed",
            ),
        ]
    )
    db_mod.replace_adjudicaciones_batch(
        {
            "FB-1": [
                Adjudicacion(licitacion_id="FB-1", nombre="Empresa A", importe_adjudicado=900.0)
            ],
            "FB-2": [
                Adjudicacion(licitacion_id="FB-2", nombre="Empresa A", importe_adjudicado=1800.0)
            ],
            "FB-3": [
                Adjudicacion(licitacion_id="FB-3", nombre="Empresa B", importe_adjudicado=450.0)
            ],
            "FB-FUERA": [
                Adjudicacion(
                    licitacion_id="FB-FUERA", nombre="Empresa C", importe_adjudicado=8000.0
                )
            ],
        }
    )


def _conteos(df: pd.DataFrame, columna: str) -> dict[str, int]:
    return {str(k): int(v) for k, v in zip(df[columna], df["n"], strict=True)}


def test_el_esperado_cubre_todas_las_consultas():
    """Sin esto, de una consulta nueva los tests de abajo no comprobarían el contenido."""
    assert set(_ESPERADO) == set(MAT_QUERIES)


def test_el_lector_devuelve_cada_consulta_materializada_con_sus_datos(tmp_db):
    """``mat_query_reader`` cede un lector y cada nombre devuelve su agregado real."""
    db_mod, _ = tmp_db
    _siembra(db_mod)

    from db.kpi_precompute import mat_query_reader

    with mat_query_reader() as leer:
        assert leer is not None, "con el adaptador de Postgres hay conexión DBAPI cruda"
        tablas = {nombre: leer(nombre) for nombre in MAT_QUERIES}

    for nombre, (columna, esperado) in _ESPERADO.items():
        assert _conteos(tablas[nombre], columna) == esperado, nombre


def test_el_export_sin_duckdb_escribe_un_parquet_por_consulta(tmp_db, monkeypatch):
    """Sin DuckDB, ``run_kpi_export_parquet`` exporta las cinco tablas vía pandas.

    ``has_duckdb`` se fuerza a ``False`` para que el test recorra el fallback
    también donde el extra ``[analytics]`` sí esté instalado.
    """
    db_mod, tmp_path = tmp_db
    _siembra(db_mod)

    escritos: dict[str, pd.DataFrame] = {}
    argumentos: list[dict[str, Any]] = []

    def to_parquet_en_memoria(self: pd.DataFrame, path: str, **kwargs: Any) -> None:
        escritos[path] = self.copy()
        argumentos.append(kwargs)

    monkeypatch.setattr("db.analytics.has_duckdb", lambda: False)
    monkeypatch.setattr(pd.DataFrame, "to_parquet", to_parquet_en_memoria)

    from scheduler.kpi_precompute import run_kpi_export_parquet

    result = run_kpi_export_parquet(output_dir=str(tmp_path))

    rutas = {nombre: str(Path(tmp_path) / f"{nombre}.parquet") for nombre in MAT_QUERIES}
    assert result["engine"] == "pandas"
    assert result["exported"] == list(rutas.values())
    assert list(escritos) == list(rutas.values())
    assert argumentos == [{"index": False, "engine": "pyarrow"}] * len(MAT_QUERIES)
    for nombre, (columna, esperado) in _ESPERADO.items():
        assert _conteos(escritos[rutas[nombre]], columna) == esperado, nombre


class _AdaptadorSinConexionCruda:
    """Conexión sin ``_conn`` ni ``connection``: ``pd.read_sql`` no tendría con qué leer."""


@contextmanager
def _connect_sin_conexion_cruda() -> Iterator[_AdaptadorSinConexionCruda]:
    yield _AdaptadorSinConexionCruda()


def test_sin_conexion_cruda_el_lector_es_none_y_el_export_no_escribe_nada(tmp_path, monkeypatch):
    """Sin conexión DBAPI en el adaptador, se cede ``None`` y el job salta cada tabla sin error.

    No toca Postgres: el doble de ``connect`` es precisamente un adaptador que
    no sirve para leer.
    """
    monkeypatch.setattr("db.database.connect", _connect_sin_conexion_cruda)

    from db.kpi_precompute import mat_query_reader

    with mat_query_reader() as leer:
        assert leer is None

    llamadas: list[Any] = []
    monkeypatch.setattr("db.analytics.has_duckdb", lambda: False)
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda self, *a, **k: llamadas.append((a, k)))

    from scheduler.kpi_precompute import run_kpi_export_parquet

    result = run_kpi_export_parquet(output_dir=str(tmp_path))

    assert result["exported"] == []
    assert result["engine"] == "pandas"
    assert llamadas == []
