"""Tests para GET /api/v1/licitaciones/{id}/eventos y GET /api/v1/eventos."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers de seed
# ---------------------------------------------------------------------------


def _seed_licitacion(id_externo: str) -> None:
    import db.database as db_mod

    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, estado, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s,%s,%s,%s,%s)",
            (id_externo, "Test licitacion", "PUB", "2026-01-01", "2026-01-01"),
        )


# ---------------------------------------------------------------------------
# GET /licitaciones/{id}/eventos — timeline
# ---------------------------------------------------------------------------


def test_eventos_timeline_no_existe(client, auth):
    """Licitacion inexistente → 404."""
    r = client.get("/api/v1/licitaciones/NOPE-999/eventos", headers=auth)
    assert r.status_code == 404
    assert "no encontrada" in r.json()["detail"].lower()


def test_eventos_timeline_existente_vacio(client, auth):
    """Licitacion existente sin eventos → 200 con items vacío."""
    _seed_licitacion("EV001")
    r = client.get("/api/v1/licitaciones/EV001/eventos", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["licitacion_id"] == "EV001"
    # items puede contener el hito de publicacion derivado del campo de la licitacion,
    # pero la lista debe existir y ser iterable
    assert isinstance(data["items"], list)


def test_eventos_timeline_sin_auth(client):
    """Sin cabecera de autenticacion → 401 o 403."""
    _seed_licitacion("EV002")
    r = client.get("/api/v1/licitaciones/EV002/eventos")
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /eventos — feed reciente
# ---------------------------------------------------------------------------


def test_eventos_tipo_invalido(client, auth):
    """tipo=INVALIDO → 422."""
    r = client.get("/api/v1/eventos?tipo=INVALIDO", headers=auth)
    assert r.status_code == 422


def test_eventos_feed_sin_filtros(client, auth):
    """GET /eventos sin filtros → 200 con items y dias."""
    r = client.get("/api/v1/eventos", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "dias" in data
    assert isinstance(data["items"], list)


def test_eventos_feed_con_tipo(client, auth):
    """GET /eventos?tipo=adjudicacion&dias=30 → 200."""
    r = client.get("/api/v1/eventos?tipo=adjudicacion&dias=30", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert data["dias"] == 30


def test_eventos_feed_dias_fuera_de_rango(client, auth):
    """dias=0 (< min=1) → 422."""
    r = client.get("/api/v1/eventos?dias=0", headers=auth)
    assert r.status_code == 422


def test_eventos_feed_tipos_validos(client, auth):
    """Todos los tipos validos del set deben devolver 200."""
    tipos_validos = [
        "adjudicacion",
        "formalizacion",
        "modificacion",
        "prorroga",
        "anulacion",
        "cambio_estado",
        "recurso",
    ]
    for tipo in tipos_validos:
        r = client.get(f"/api/v1/eventos?tipo={tipo}", headers=auth)
        assert r.status_code == 200, f"tipo={tipo!r} devolvio {r.status_code}"


def test_eventos_feed_acepta_el_ambito_global(client, auth):
    """Los filtros generales del Resumen viajan al feed sin romperlo."""
    r = client.get(
        "/api/v1/eventos?ccaa=Madrid&tecnologia=SAP&estado=PUB&importe_min=1000"
        "&solo_abiertas=true&q=mantenimiento&fecha_desde=2026-01-01&fecha_hasta=2026-12-31",
        headers=auth,
    )
    assert r.status_code == 200
    assert isinstance(r.json()["items"], list)


def test_eventos_feed_fecha_invalida(client, auth):
    """fecha_desde no ISO → 422 (no una query con basura dentro)."""
    r = client.get("/api/v1/eventos?fecha_desde=ayer", headers=auth)
    assert r.status_code == 422


def test_eventos_feed_importe_min_negativo(client, auth):
    """importe_min < 0 → 422."""
    r = client.get("/api/v1/eventos?importe_min=-1", headers=auth)
    assert r.status_code == 422
