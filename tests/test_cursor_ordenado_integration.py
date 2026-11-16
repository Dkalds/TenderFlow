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


_FECHADAS_DESC = ["C-07", "C-06", "C-05", "C-04", "C-03", "C-02", "C-01"]


def _sembrar_fecha(fecha: str | None, *ids: str) -> None:
    from db.database import connect

    with connect() as c:
        for id_externo in ids:
            c.execute(
                "INSERT INTO licitaciones "
                "(id_externo, titulo, fecha_publicacion, tecnologia, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s, %s)",
                (id_externo, f"Fecha {fecha!r} {id_externo}", fecha, "SAP", "2026-01-01"),
            )
        c.commit()


def _recorrer_por_defecto(cliente: Any) -> list[str]:
    """Todas las páginas del orden por defecto (sin ``sort``), de dos en dos."""
    ids: list[str] = []
    cursor: str | None = None
    for _ in range(20):
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        resp = cliente.get("/api/v1/licitaciones/cursor", params=params)
        assert resp.status_code == 200, resp.text
        pagina = resp.json()
        ids.extend(item["id_externo"] for item in pagina["items"])
        if not pagina["has_more"]:
            return ids
        cursor = pagina["next_cursor"]
    raise AssertionError(f"la paginación no terminó: {ids}")


def test_orden_por_defecto_atraviesa_las_fechas_nulas(sembrado: Any) -> None:
    """Una página que acaba en fecha nula no puede dejar vacía la siguiente.

    El orden por defecto es ``fecha_publicacion DESC`` con los nulos delante
    (el de ``idx_lic_cursor``), y el cursor de una fila sin fecha viaja como
    ``|id``: tiene que seguir por la cola de nulos y luego por las fechadas.
    """
    _sembrar_fecha(None, "C-08", "C-09", "C-10")

    assert _recorrer_por_defecto(sembrado) == ["C-10", "C-09", "C-08", *_FECHADAS_DESC]


def test_orden_por_defecto_con_fechas_vacias_heredadas_termina(sembrado: Any) -> None:
    """``''`` guardado y fecha nula viajan igual en el cursor (``|id``).

    El CHECK de formato de v59 es ``NOT VALID``: el histórico puede tener
    ``''``, que en el texto ordena **detrás** de todas las fechadas. Leer
    ``|id`` siempre como «nulo» volvía a empezar por las fechadas al acabar
    una página en una fila ``''``, y el recorrido no terminaba nunca.
    """
    from db.database import connect

    restriccion = "ck_licitaciones_fecha_publicacion_iso"
    with connect() as c:
        c.execute(f"ALTER TABLE licitaciones DROP CONSTRAINT {restriccion}")
        c.commit()
    _sembrar_fecha(None, "C-08", "C-09", "C-10")
    _sembrar_fecha("", "V-01", "V-02", "V-03")
    with connect() as c:  # el estado de producción: CHECK presente, histórico sin validar
        c.execute(
            f"ALTER TABLE licitaciones ADD CONSTRAINT {restriccion} "
            "CHECK (fecha_publicacion IS NULL OR fecha_publicacion ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}') "
            "NOT VALID"
        )
        c.commit()

    assert _recorrer_por_defecto(sembrado) == [
        "C-10",
        "C-09",
        "C-08",
        *_FECHADAS_DESC,
        "V-03",
        "V-02",
        "V-01",
    ]


def test_orden_por_defecto_con_la_sombra_atraviesa_las_fechas_nulas(
    sembrado: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con ``NUCLEO_TIPADO_LECTURA`` el cursor ``|id`` no puede llegar a un cast de ``''``."""
    from config import settings
    from db.database import connect

    _sembrar_fecha(None, "C-08", "C-09", "C-10")
    with connect() as c:
        c.execute(
            "UPDATE licitaciones SET fecha_publicacion_ts = fecha_publicacion::timestamptz "
            "WHERE fecha_publicacion IS NOT NULL"
        )
        c.commit()
    monkeypatch.setattr(settings, "NUCLEO_TIPADO_LECTURA", True, raising=False)

    assert _recorrer_por_defecto(sembrado) == ["C-10", "C-09", "C-08", *_FECHADAS_DESC]


def test_un_cursor_de_otro_orden_es_400(sembrado: Any) -> None:
    primera = sembrado.get("/api/v1/licitaciones/cursor", params={"sort": "importe", "limit": 2})
    cursor = primera.json()["next_cursor"]
    resp = sembrado.get(
        "/api/v1/licitaciones/cursor", params={"sort": "titulo", "cursor": cursor, "limit": 2}
    )
    assert resp.status_code == 400
