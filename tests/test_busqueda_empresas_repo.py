"""La paleta ⌘K encuentra empresas del maestro (``BusquedaRepository``).

Hasta 2026-11 las dos consultas de empresas pedían ``id`` y ``nif``, columnas
que ``empresas`` no tiene (son ``empresa_id`` y ``nif_canonico``): fallaban
siempre, y ``services.busqueda_global`` —fail-open por tipo— lo tragaba. Los
tests de la búsqueda global usan un repositorio falso, así que nadie lo veía.
"""

from __future__ import annotations

from typing import Any

import pytest

from db.repositories.busqueda import BusquedaRepository

NIF = "B12345678"  # pragma: allowlist secret  NIF de prueba, no un secreto


@pytest.fixture()
def maestro(tmp_db: Any) -> int:
    from db.database import connect

    with connect() as c:
        return int(
            c.execute(
                "INSERT INTO empresas (nombre_canonico, nif_canonico) "
                "VALUES ('Cámara Sistemas SL', %s) RETURNING empresa_id",
                (NIF,),
            ).fetchone()[0]
        )


def test_busca_por_nombre_plegando_tildes(maestro: int) -> None:
    filas = BusquedaRepository().empresas("camara", 5)

    assert filas == [{"id": maestro, "titulo": "Cámara Sistemas SL", "subtitulo": NIF}]


def test_identifica_por_nif(maestro: int) -> None:
    assert BusquedaRepository().empresa_por_nif(f" {NIF.lower()} ") == {
        "id": maestro,
        "nombre_canonico": "Cámara Sistemas SL",
        "nif": NIF,
    }
    assert BusquedaRepository().empresa_por_nif("B00000000") is None
