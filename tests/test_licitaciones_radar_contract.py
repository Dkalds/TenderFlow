"""Lo que el Radar necesita del listado de licitaciones.

El Radar ("qué merece atención ahora") se apoya en ``/api/v1/licitaciones``.
Dos cosas tienen que ser ciertas para que la página signifique algo, y ninguna
lo era: que el orden por defecto devuelva lo más reciente primero, y que el
resumen incluya la fecha límite — sin ella no hay urgencia que mostrar.
"""

from __future__ import annotations

from db.repositories.licitaciones import LicitacionRepository

_ROWS = (
    ("RADAR-OLD", "2020-01-01", "2020-06-01T00:00:00+00:00"),
    ("RADAR-MID", "2023-01-01", "2023-06-01T00:00:00+00:00"),
    ("RADAR-NEW", "2026-07-01", "2026-12-01T00:00:00+00:00"),
)


def _seed(db_mod) -> None:
    with db_mod.connect() as conn:
        for id_externo, publicacion, limite in _ROWS:
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, fecha_publicacion, "
                "fecha_limite, fecha_extraccion, tecnologia) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    id_externo,
                    f"Licitación {id_externo}",
                    publicacion,
                    limite,
                    "2026-07-30T00:00:00+00:00",
                    "SAP",
                ),
            )


def test_the_default_order_is_newest_first(tmp_db):
    db_mod, _ = tmp_db
    _seed(db_mod)

    items, _ = LicitacionRepository().list_paginated(limit=10, with_total=False)

    assert [row["id_externo"] for row in items] == ["RADAR-NEW", "RADAR-MID", "RADAR-OLD"]


def test_the_minus_prefix_on_dates_means_oldest_first(tmp_db):
    """``-fecha_publicacion`` es ascendente, al revés que ``-importe``.

    La asimetría es deliberada (el orden natural de una fecha es descendente),
    pero es una trampa: pedir ``sort=-fecha_publicacion`` creyendo que es "lo
    más nuevo" devuelve justo lo contrario. El Radar caía en ella.
    """
    db_mod, _ = tmp_db
    _seed(db_mod)
    repo = LicitacionRepository()

    oldest_first, _ = repo.list_paginated(limit=10, sort="-fecha_publicacion", with_total=False)
    newest_first, _ = repo.list_paginated(limit=10, sort="fecha_publicacion", with_total=False)

    assert [row["id_externo"] for row in oldest_first] == ["RADAR-OLD", "RADAR-MID", "RADAR-NEW"]
    assert [row["id_externo"] for row in newest_first] == ["RADAR-NEW", "RADAR-MID", "RADAR-OLD"]


def test_the_summary_carries_the_deadline_the_radar_renders(tmp_db):
    db_mod, _ = tmp_db
    _seed(db_mod)

    items, _ = LicitacionRepository().list_paginated(limit=10, with_total=False)

    assert items[0]["fecha_limite"] is not None
    assert str(items[0]["fecha_limite"]).startswith("2026-12-01")


def test_the_api_serialises_the_deadline_in_the_listing(client, api_db, auth):
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_publicacion, "
            "fecha_limite, fecha_extraccion, tecnologia) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "RADAR-API",
                "Licitación radar",
                "2026-07-01",
                "2026-12-01T00:00:00+00:00",
                "2026-07-30T00:00:00+00:00",
                "SAP",
            ),
        )

    listed = client.get("/api/v1/licitaciones", params={"limit": 5}, headers=auth)

    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["id_externo"] == "RADAR-API"
    assert item["fecha_limite"].startswith("2026-12-01")
