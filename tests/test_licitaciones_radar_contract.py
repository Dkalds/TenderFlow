"""Lo que el Radar necesita del listado de licitaciones.

El Radar ("qué merece atención ahora") se apoya en ``/api/v1/licitaciones``.
Tres cosas tienen que ser ciertas para que la página signifique algo, y ninguna
lo era: que el orden por defecto devuelva lo más reciente primero, que el
resumen incluya la fecha límite —sin ella no hay urgencia que mostrar— y que
los expedientes ya cerrados no ocupen sitio en la bandeja.
"""

from __future__ import annotations

from db.repositories.licitaciones import LicitacionRepository

_ROWS = (
    ("RADAR-OLD", "2020-01-01", "2020-06-01T00:00:00+00:00"),
    ("RADAR-MID", "2023-01-01", "2023-06-01T00:00:00+00:00"),
    ("RADAR-NEW", "2026-07-01", "2026-12-01T00:00:00+00:00"),
)

# Una fila por estado terminal, más los abiertos que deben sobrevivir al filtro.
# ``None`` está a propósito: sin estado no hay evidencia de cierre, y un
# ``NOT IN`` sin COALESCE se la comería en silencio.
_ESTADO_ROWS = (
    ("EST-PUB", "PUB"),
    ("EST-EV", "EV"),
    ("EST-NULL", None),
    ("EST-RES", "RES"),
    ("EST-ADJ", "ADJ"),
    ("EST-ANUL", "ANUL"),
)


def _seed(db_mod) -> None:
    with db_mod.connect() as conn:
        for id_externo, publicacion, limite in _ROWS:
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, fecha_publicacion, "
                "fecha_limite, fecha_extraccion, tecnologia) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    id_externo,
                    f"Licitación {id_externo}",
                    publicacion,
                    limite,
                    "2026-07-30T00:00:00+00:00",
                    "SAP",
                ),
            )


def _seed_estados(db_mod) -> None:
    """Siembra un expediente por estado.

    El título lleva ``bandeja`` para que el test de la rama FTS tenga un
    término que buscar: ``search_vector`` es columna generada, así que un
    INSERT normal ya la rellena.
    """
    with db_mod.connect() as conn:
        for id_externo, estado in _ESTADO_ROWS:
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_publicacion, "
                "fecha_extraccion, tecnologia) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    id_externo,
                    f"Licitación bandeja {id_externo}",
                    estado,
                    "2026-07-01",
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


def test_only_open_tenders_leaves_out_the_terminal_states(tmp_db):
    """Resuelta, adjudicada y anulada no son oportunidades.

    El Radar propone sobre qué actuar hoy. Un expediente en estado terminal ya
    no admite oferta: seguirlo o abrirle una oportunidad al equipo no lleva a
    ninguna parte, así que ocupa un sitio de los 24 sin poder devolver nada.
    """
    db_mod, _ = tmp_db
    _seed_estados(db_mod)

    items, _ = LicitacionRepository().list_paginated(limit=10, solo_abiertas=True, with_total=False)

    assert sorted(row["id_externo"] for row in items) == ["EST-EV", "EST-NULL", "EST-PUB"]


def test_a_state_the_source_has_not_documented_yet_counts_as_open(tmp_db):
    """Se enumera el cierre, nunca la apertura.

    Si el filtro fuese una lista blanca (``estado IN ('PUB','EV')``), un código
    nuevo de PLACSP desaparecería del Radar sin que nadie se entere. Al revés
    —aparecer de más— se ve y se corrige.
    """
    db_mod, _ = tmp_db
    _seed_estados(db_mod)
    with db_mod.connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_publicacion, "
            "fecha_extraccion, tecnologia) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                "EST-FUTURO",
                "Licitación con estado nuevo",
                "XYZ",
                "2026-07-02",
                "2026-07-30T00:00:00+00:00",
                "SAP",
            ),
        )

    items, _ = LicitacionRepository().list_paginated(limit=10, solo_abiertas=True, with_total=False)

    assert "EST-FUTURO" in {row["id_externo"] for row in items}


def test_the_filter_survives_the_full_text_search_branch(tmp_db):
    """Con ``q``, el listado cambia de motor — y el filtro tiene que ir con él.

    ``list_paginated`` deriva a ``_list_fts`` cuando hay término de búsqueda,
    porque ``MATCH`` no tiene equivalente en SQLAlchemy Core. Son dos caminos
    que construyen el WHERE por separado: si el criterio sólo viaja en uno,
    buscar dentro del Radar resucitaría los expedientes cerrados.
    """
    db_mod, _ = tmp_db
    _seed_estados(db_mod)

    items, _ = LicitacionRepository().list_paginated(
        q="bandeja", limit=10, solo_abiertas=True, with_total=False
    )

    assert sorted(row["id_externo"] for row in items) == ["EST-EV", "EST-NULL", "EST-PUB"]


def test_without_the_flag_the_listing_still_returns_everything(tmp_db):
    """El filtro es opt-in: el resto de páginas siguen viendo el corpus entero."""
    db_mod, _ = tmp_db
    _seed_estados(db_mod)

    items, _ = LicitacionRepository().list_paginated(limit=10, with_total=False)

    assert len(items) == len(_ESTADO_ROWS)


def test_the_api_exposes_the_open_only_filter_to_the_radar(client, api_db, auth):
    from db.database import connect

    with connect() as conn:
        for id_externo, estado in (("API-PUB", "PUB"), ("API-RES", "RES")):
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_publicacion, "
                "fecha_extraccion, tecnologia) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    id_externo,
                    f"Licitación {id_externo}",
                    estado,
                    "2026-07-01",
                    "2026-07-30T00:00:00+00:00",
                    "SAP",
                ),
            )

    listed = client.get(
        "/api/v1/licitaciones",
        params={"limit": 50, "solo_abiertas": "true"},
        headers=auth,
    )

    assert listed.status_code == 200
    ids = {item["id_externo"] for item in listed.json()["items"]}
    assert "API-PUB" in ids
    assert "API-RES" not in ids


def test_the_api_serialises_the_deadline_in_the_listing(client, api_db, auth):
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_publicacion, "
            "fecha_limite, fecha_extraccion, tecnologia) VALUES (%s, %s, %s, %s, %s, %s)",
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
