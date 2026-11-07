"""Limpieza de los adjudicatarios compuestos de PSCP (``db.empresas.limpiar_adjudicatarios_compuestos``).

Reproduce lo que dejó en la base el parser anterior al 2026-11-06: una
adjudicación con dos empresas unidas por ``||`` enlazada a una empresa
compuesta, y otra empresa compuesta que ya no usa nada (resto de una fila
purgada). Tras la limpieza, cada empresa tiene su fila, la resolución las
enlaza a sus empresas reales por NIF y las compuestas desaparecen.
"""

from __future__ import annotations

from typing import Any

import pytest

from db.database import connect
from db.upsert import Adjudicacion, Licitacion, replace_adjudicaciones_batch, upsert_licitaciones

_LIC = "pscp:6f1c2a3b-0d4e-4f5a-9b8c-7d6e5f4a3b2c:CTTI-2026-00123"


def _empresa(c: Any, nombre: str, nif: str | None) -> int:
    return int(
        c.execute(
            "INSERT INTO empresas (nombre_canonico, nif_canonico) VALUES (%s, %s) "
            "RETURNING empresa_id",
            (nombre, nif),
        ).fetchone()[0]
    )


@pytest.fixture()
def compuestas(tmp_db: Any) -> dict[str, int]:
    upsert_licitaciones(
        [
            Licitacion(
                id_externo=_LIC, titulo="Suport SAP", fecha_publicacion="2026-05-20", fuente="pscp"
            )
        ]
    )
    replace_adjudicaciones_batch(
        {
            _LIC: [
                Adjudicacion(
                    licitacion_id=_LIC,
                    nombre="SEIDOR SL||INETUM ESPAÑA SA",
                    nif="B61420352||A28237469",
                    importe_adjudicado=500000.0,
                    n_ofertas_recibidas=3,
                    fecha_adjudicacion="2026-08-01",
                )
            ]
        }
    )
    with connect() as c:
        ids = {
            "compuesta": _empresa(c, "SEIDOR SL||INETUM ESPAÑA SA", "B61420352||A28237469"),
            "huerfana": _empresa(c, "A SL||B SL", "B1||B2"),
            "seidor": _empresa(c, "SEIDOR SL", "B61420352"),
            "inetum": _empresa(c, "INETUM ESPAÑA SA", "A28237469"),
        }
        c.execute(
            "INSERT INTO empresa_aliases (empresa_id, alias_normalizado) VALUES (%s, %s)",
            (ids["huerfana"], "A SL B SL"),
        )
        c.execute("UPDATE adjudicaciones SET empresa_id = %s", (ids["compuesta"],))
    return ids


def _filas() -> list[tuple[Any, ...]]:
    with connect() as c:
        return [
            tuple(r)
            for r in c.execute(
                "SELECT nombre, nif, importe_adjudicado, n_ofertas_recibidas, fecha_adjudicacion, "
                "       empresa_id FROM adjudicaciones ORDER BY nombre"
            ).fetchall()
        ]


def test_sin_aplicar_solo_cuenta(compuestas: dict[str, int]) -> None:
    from db.empresas import limpiar_adjudicatarios_compuestos

    antes = _filas()
    recuento = limpiar_adjudicatarios_compuestos(aplicar=False)

    assert (recuento.adjudicaciones_compuestas, recuento.adjudicaciones_nuevas) == (1, 2)
    assert recuento.empresas_borradas == 2
    assert _filas() == antes


def test_parte_borra_las_compuestas_y_enlaza_por_nif(compuestas: dict[str, int]) -> None:
    from scripts.partir_adjudicatarios_pscp import main

    assert main(["--apply"]) == 0

    # Una fila por empresa, enlazada a la real; el importe único no se reparte.
    assert _filas() == [
        ("INETUM ESPAÑA SA", "A28237469", None, 3, "2026-08-01", compuestas["inetum"]),
        ("SEIDOR SL", "B61420352", None, 3, "2026-08-01", compuestas["seidor"]),
    ]
    with connect() as c:
        quedan = {r[0] for r in c.execute("SELECT nombre_canonico FROM empresas").fetchall()}
        alias_huerfano = c.execute(
            "SELECT count(*) FROM empresa_aliases WHERE empresa_id = %s",
            (compuestas["huerfana"],),
        ).fetchone()[0]
    assert quedan == {"SEIDOR SL", "INETUM ESPAÑA SA"}
    assert alias_huerfano == 0


def test_una_segunda_pasada_no_encuentra_nada(compuestas: dict[str, int]) -> None:
    from db.empresas import limpiar_adjudicatarios_compuestos

    limpiar_adjudicatarios_compuestos(aplicar=True)
    antes = _filas()

    recuento = limpiar_adjudicatarios_compuestos(aplicar=True)

    assert recuento == type(recuento)(0, 0, 0)
    assert _filas() == antes
