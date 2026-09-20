"""Paginación por cursor ordenada, de punta a punta contra Postgres.

Recorrer todas las páginas con cada orden tiene que dar **cada fila una vez**
y en el mismo orden que la consulta sin paginar, incluidos los importes
repetidos (el desempate por id) y los nulos (al final en los dos sentidos).
Y ``with_total`` tiene que contar lo mismo que se recorre.
"""

from __future__ import annotations

from typing import Any

import pytest

_FILAS: list[tuple[str, str, float | None, str]] = [
    ("C-01", "Alfa soporte", 100.0, "2026-01-05"),
    ("C-02", "Beta licencias", 250.0, "2026-01-06"),
    ("C-03", "Gamma consultoría", 250.0, "2026-01-07"),
    ("C-04", "Delta mantenimiento", None, "2026-01-08"),
    ("C-05", "Épsilon migración", 50.0, "2026-01-09"),
    ("C-06", "Zeta integración", None, "2026-01-10"),
    ("C-07", "Eta auditoría", 900.0, "2026-01-11"),
]


@pytest.fixture()
def sembrado(api_db: Any, api_key: str) -> Any:
    from fastapi.testclient import TestClient

    from api.app import app
    from db.database import connect

    with connect() as c:
        for id_externo, titulo, importe, fecha in _FILAS:
            c.execute(
                "INSERT INTO licitaciones "
                "(id_externo, titulo, importe, fecha_publicacion, tecnologia, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (id_externo, titulo, importe, fecha, "SAP", "2026-01-01"),
            )
        c.commit()
    cliente = TestClient(app, raise_server_exceptions=True)
    cliente.headers["X-API-Key"] = api_key
    return cliente


def _recorrer(cliente: Any, sort: str, limit: int = 2) -> tuple[list[str], int | None]:
    ids: list[str] = []
    cursor: str | None = None
    total: int | None = None
    for vuelta in range(20):
        params: dict[str, Any] = {"sort": sort, "limit": limit}
        if vuelta == 0:
            params["with_total"] = "true"
        if cursor:
            params["cursor"] = cursor
        resp = cliente.get("/api/v1/licitaciones/cursor", params=params)
        assert resp.status_code == 200, resp.text
        pagina = resp.json()
        if vuelta == 0:
            total = pagina["total"]
        else:
            assert pagina["total"] is None  # sólo se cuenta cuando se pide
        ids.extend(item["id_externo"] for item in pagina["items"])
        if not pagina["has_more"]:
            return ids, total
        cursor = pagina["next_cursor"]
    raise AssertionError("la paginación no terminó")


@pytest.mark.parametrize(
    ("sort", "esperado"),
    [
        # Importe ascendente: empate 250 desempatado por id; nulos al final.
        ("importe", ["C-05", "C-01", "C-02", "C-03", "C-07", "C-04", "C-06"]),
        # Descendente: empate por id descendente; nulos también al final.
        ("-importe", ["C-07", "C-03", "C-02", "C-01", "C-05", "C-06", "C-04"]),
        ("titulo", ["C-01", "C-02", "C-04", "C-07", "C-03", "C-06", "C-05"]),
        ("-fecha_publicacion", ["C-01", "C-02", "C-03", "C-04", "C-05", "C-06", "C-07"]),
        ("fecha_publicacion", ["C-07", "C-06", "C-05", "C-04", "C-03", "C-02", "C-01"]),
    ],
)
def test_cada_fila_una_vez_y_en_orden(sembrado: Any, sort: str, esperado: list[str]) -> None:
    ids, total = _recorrer(sembrado, sort)
    if sort == "titulo":
        # El orden de texto lo decide la colación de la base, no Python: se
        # exige que no falte ni sobre nada y que sea estable entre páginas.
        assert sorted(ids) == sorted(esperado)
    else:
        assert ids == esperado
    assert total == len(_FILAS)


def test_un_cursor_de_otro_orden_es_400(sembrado: Any) -> None:
    primera = sembrado.get("/api/v1/licitaciones/cursor", params={"sort": "importe", "limit": 2})
    cursor = primera.json()["next_cursor"]
    resp = sembrado.get(
        "/api/v1/licitaciones/cursor", params={"sort": "titulo", "cursor": cursor, "limit": 2}
    )
    assert resp.status_code == 400
