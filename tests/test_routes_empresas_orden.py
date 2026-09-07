"""Orden y paginación de ``GET /api/v1/empresas``.

La cabecera ordenable y el «1–12 de N» del buscador del maestro sólo dicen la
verdad si el orden y el recuento salen del servidor: ordenar la página ya
traída reordena 50 filas de 1.284, y contar `len(items)` cuenta el tamaño de
la página, no el del filtro. Estos tests fijan las dos cosas.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def maestro(api_db):
    """Cinco empresas con agregados distintos y un NIF ausente.

    Los importes y los conteos se cruzan a propósito (la que más contratos
    tiene no es la que más importe suma), así que un orden por la columna
    equivocada no puede pasar por bueno. Las mayúsculas también están
    mezcladas: el maestro guarda el nombre tal y como viene de la fuente
    (``db/empresas.py``: ``nombre_original.strip()``), así que conviven
    «alfa Consultores» y «OMEGA REDES».
    """
    from db.database import connect

    filas = [
        # (nombre, nif, contratos, importe por contrato)
        ("Delta Sistemas", "A00000001", 1, 900.0),
        ("alfa Consultores", "A00000002", 4, 100.0),
        ("Beta Tecnologías", None, 3, 200.0),
        ("Gamma Servicios", "A00000004", 2, 300.0),
        ("OMEGA REDES", "A00000005", 1, 50.0),
    ]
    ids: dict[str, int] = {}
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
            ("LIC-ORD-1", "Licitación de prueba", "2026-01-15"),
        )
        for nombre, nif, contratos, importe in filas:
            row = c.execute(
                "INSERT INTO empresas (nombre_canonico, nif_canonico) VALUES (%s, %s) "
                "RETURNING empresa_id",
                (nombre, nif),
            ).fetchone()
            empresa_id = int(row[0])
            ids[nombre] = empresa_id
            for _ in range(contratos):
                c.execute(
                    "INSERT INTO adjudicaciones "
                    "(licitacion_id, nombre, importe_adjudicado, empresa_id, fecha_extraccion) "
                    "VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)",
                    ("LIC-ORD-1", nombre, importe, empresa_id),
                )
    return ids


def _nombres(payload: dict) -> list[str]:
    return [item["nombre_canonico"] for item in payload["items"]]


def test_orden_por_defecto_es_importe_desc(client, auth, maestro):
    """Sin `sort`, el maestro sigue llegando por importe descendente."""
    r = client.get("/api/v1/empresas", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["sort"] == "importe"
    assert data["order"] == "desc"
    # Delta 900 · Beta 600 · Gamma 600 · alfa 400 · OMEGA 50. Beta y Gamma
    # empatan, así que se fijan la cabeza y la cola, que es lo que el empate
    # no toca.
    assert _nombres(data)[0] == "Delta Sistemas"
    assert _nombres(data)[-1] == "OMEGA REDES"


def test_orden_por_contratos_no_es_el_de_importe(client, auth, maestro):
    """`sort=contratos` ordena por número de adjudicaciones, no por importe."""
    r = client.get("/api/v1/empresas?sort=contratos&order=desc", headers=auth)
    assert r.status_code == 200
    assert _nombres(r.json())[0] == "alfa Consultores"


def test_orden_por_nombre_ignora_mayusculas(client, auth, maestro):
    """`sort=nombre` compara sin mayúsculas: «alfa» va antes que «Beta».

    Con un `ORDER BY` sobre el texto crudo y colación C, «alfa» en minúscula
    caería al final de la lista y «OMEGA REDES» al principio, que es
    exactamente lo que un usuario que pulsa «Empresa» no espera ver.
    """
    r = client.get("/api/v1/empresas?sort=nombre&order=asc", headers=auth)
    assert r.status_code == 200
    assert _nombres(r.json()) == [
        "alfa Consultores",
        "Beta Tecnologías",
        "Delta Sistemas",
        "Gamma Servicios",
        "OMEGA REDES",
    ]


def test_nif_ausente_va_al_final_en_los_dos_sentidos(client, auth, maestro):
    """Un NIF nulo no es «el menor»: es el dato que falta, y va al final.

    Si encabezara el orden ascendente, la primera página del maestro sería la
    de las filas de las que no se sabe nada — justo al revés de para lo que
    sirve ordenar por NIF.
    """
    for sentido in ("asc", "desc"):
        r = client.get(f"/api/v1/empresas?sort=nif&order={sentido}", headers=auth)
        assert r.status_code == 200
        assert _nombres(r.json())[-1] == "Beta Tecnologías", sentido


def test_total_cuenta_el_filtro_y_no_la_pagina(client, auth, maestro):
    """`total` es el tamaño del filtro; `items` el de la página."""
    r = client.get("/api/v1/empresas?limit=2", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 2
    assert data["total"] == 5

    # `q` se compara en mayúsculas contra el nombre guardado, que es como ya
    # buscaba la ruta antes de este cambio; lo que se fija aquí es el total,
    # no la semántica de la búsqueda.
    r = client.get("/api/v1/empresas?q=omega", headers=auth)
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_paginacion_no_pierde_ni_repite_filas(client, auth, maestro):
    """Recorrer el maestro de dos en dos lo cubre entero, sin solapes.

    El desempate por `empresa_id` es lo que lo garantiza cuando hay importes
    empatados (Beta y Gamma suman 600 las dos): sin él, dos filas iguales
    pueden cruzarse entre páginas y una de las dos no sale en ninguna.
    """
    vistas: list[str] = []
    for offset in (0, 2, 4):
        pagina = client.get(f"/api/v1/empresas?limit=2&offset={offset}", headers=auth).json()
        vistas.extend(_nombres(pagina))
    assert sorted(vistas) == sorted(maestro)


def test_sort_desconocido_es_422(client, auth, maestro):
    """Una columna fuera del contrato se rechaza en el borde, no en el SQL."""
    r = client.get("/api/v1/empresas?sort=importe_total%3B+DROP", headers=auth)
    assert r.status_code == 422
