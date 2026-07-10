"""Tests para GET /api/v1/licitaciones/{id}/prediccion-baja."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Helpers de seed
# ---------------------------------------------------------------------------


def _seed_licitacion(id_externo: str, *, importe: float | None = None) -> None:
    import db.database as db_mod

    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, estado, importe, fecha_publicacion, fecha_extraccion) "
            "VALUES (?,?,?,?,?,?)",
            (id_externo, "Test prediccion", "PUB", importe, "2026-01-01", "2026-01-01"),
        )


def _seed_adjudicacion(licitacion_id: str, importe_adjudicado: float) -> None:
    import db.database as db_mod

    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, importe_adjudicado, fecha_adjudicacion, fecha_extraccion) "
            "VALUES (?, 'Empresa X', ?, '2026-02-01', '2026-02-01')",
            (licitacion_id, importe_adjudicado),
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_predicciones_no_existe(client, auth):
    """Licitacion inexistente → 404 (sin prediccion en batch)."""
    r = client.get("/api/v1/licitaciones/NO-EXISTE-999/prediccion-baja", headers=auth)
    assert r.status_code == 404
    assert "predicci" in r.json()["detail"].lower()


def test_predicciones_licitacion_existente_sin_batch(client, auth):
    """Licitacion creada pero batch aun no ha corrido → 404 (sin fila en predicciones_baja)."""
    _seed_licitacion("PRED001")
    r = client.get("/api/v1/licitaciones/PRED001/prediccion-baja", headers=auth)
    # La prediccion solo existe tras el batch nocturno; antes devuelve 404
    assert r.status_code == 404


def test_predicciones_sin_auth(client):
    """Sin cabecera de autenticacion → 401 o 403."""
    r = client.get("/api/v1/licitaciones/CUALQUIERA/prediccion-baja")
    assert r.status_code in (401, 403)


def test_predicciones_con_batch_seed(client, auth):
    """Si existe una fila en predicciones_baja → 200 con estructura correcta."""
    import db.database as db_mod

    _seed_licitacion("PRED002")

    # Insertar una prediccion manual simulando el batch
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO predicciones_baja "
            "(licitacion_id, p10, p50, p90, computed_at) "
            "VALUES (?,?,?,?,?)",
            ("PRED002", 0.05, 0.12, 0.20, "2026-01-01T00:00:00"),
        )

    r = client.get("/api/v1/licitaciones/PRED002/prediccion-baja", headers=auth)
    assert r.status_code == 200
    data = r.json()
    # Verificar que la respuesta contiene los percentiles de baja
    assert "p50" in data or "licitacion_id" in data


def test_predicciones_adjudicada_con_estimacion_previa(client, auth):
    """Adjudicada + fila previa en predicciones_baja → compara estimado vs real."""
    import db.database as db_mod

    _seed_licitacion("PRED003", importe=100_000)
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO predicciones_baja "
            "(licitacion_id, p10, p50, p90, computed_at) "
            "VALUES (?,?,?,?,?)",
            ("PRED003", 0.05, 0.12, 0.20, "2026-01-15T00:00:00"),
        )
    _seed_adjudicacion("PRED003", 88_000)  # baja real = 12%

    r = client.get("/api/v1/licitaciones/PRED003/prediccion-baja", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["p50"] == 0.12
    assert data["baja_real"] == pytest.approx(0.12)
    assert data["importe_adjudicado"] == 88_000


def test_predicciones_adjudicada_sin_estimacion_previa(client, auth):
    """Adjudicada sin fila en predicciones_baja (batch nunca corrió) → solo baja real."""
    _seed_licitacion("PRED004", importe=50_000)
    _seed_adjudicacion("PRED004", 40_000)  # baja real = 20%

    r = client.get("/api/v1/licitaciones/PRED004/prediccion-baja", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "p50" not in data
    assert data["baja_real"] == pytest.approx(0.2)
    assert data["importe_adjudicado"] == 40_000
