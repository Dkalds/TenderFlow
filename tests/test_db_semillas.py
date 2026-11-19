"""Escrituras de los sembradores (``db/semillas.py``) contra Postgres."""

from __future__ import annotations

from db.database import connect
from db.semillas import borrar_semilla_dev, insertar_negativos, upsert_predicciones_demo


def _negativo(id_externo: str) -> tuple[object, ...]:
    # Orden de `scraper.seed_negatives._collect_negatives_from_month`.
    return (
        id_externo,
        "Suministro de mobiliario",
        "Sillas y mesas",
        "Ayuntamiento de Prueba",
        12000.0,
        "EUR",
        "39100000",
        "Suministros",
        "PUB",
        "2026-10-01",
        "2026-10-02T09:00:00+02:00",
        "https://contrataciondelestado.es/x",
        "Madrid",
        "ES300",
        "Comunidad de Madrid",
        12,
        "MON",
        None,
        None,
        None,
        "L01280796",
    )


def test_insertar_negativos_no_duplica_y_guarda_la_fecha_de_la_fuente(tmp_db) -> None:
    filas = [_negativo("NEG-1"), _negativo("NEG-2")]

    assert insertar_negativos(filas) == (2, 0)
    assert insertar_negativos(filas) == (0, 2)

    with connect() as c:
        fila = c.execute(
            "SELECT fecha_actualizacion_fuente, url, organo_ref_fuente, tecnologia, "
            "raw_keywords, fecha_extraccion IS NOT NULL "
            "FROM licitaciones WHERE id_externo = 'NEG-1'"
        ).fetchone()
    assert fila[0] == "2026-10-02T09:00:00+02:00"
    assert fila[1] == "https://contrataciondelestado.es/x"
    assert fila[2] == "L01280796"
    assert fila[3] is None
    assert fila[4] is None
    assert fila[5] is True


def test_insertar_negativos_sin_filas_no_abre_conexion(tmp_db) -> None:
    assert insertar_negativos([]) == (0, 0)


def test_predicciones_demo_se_actualizan_y_el_reset_las_borra(tmp_db) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES ('SEED-1', 'Demo', 'seed', '2026-01-01')"
        )
    upsert_predicciones_demo([("SEED-1", 0.1, 0.2, 0.3, 0, "2026-01-01T00:00:00Z")])
    upsert_predicciones_demo([("SEED-1", 0.2, 0.3, 0.4, 0, "2026-01-02T00:00:00Z")])

    with connect() as c:
        filas = c.execute(
            "SELECT p50 FROM predicciones_baja WHERE licitacion_id = 'SEED-1'"
        ).fetchall()
    assert [round(float(f[0]), 2) for f in filas] == [0.3]

    borrar_semilla_dev()

    with connect() as c:
        quedan = c.execute(
            "SELECT (SELECT COUNT(*) FROM predicciones_baja), "
            "(SELECT COUNT(*) FROM licitaciones WHERE fuente = 'seed')"
        ).fetchone()
    assert tuple(quedan) == (0, 0)
