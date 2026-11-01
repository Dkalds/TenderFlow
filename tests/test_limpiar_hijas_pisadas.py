"""Hijas que una pisada de PLACSP dejó en la fila superviviente (fase 4 del RFC, pasos 1 y 2).

``db.repositories.identidad.limpiar_hijas_pisadas`` borra lo que la reingesta no
reescribió en las filas pisadas y los documentos que también cuelgan de la fila
hermana del otro órgano; ``scripts/limpiar_hijas_pisadas_placsp.py`` decide qué
filas entran (solo las pisadas seguras del inventario).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

_DESDE = "2026-10-31T15:37:00"
_ANTES = "2026-10-20T10:00:00+00:00"
_DESPUES = "2026-10-31T16:00:00+00:00"

#: La superviviente (el órgano 222 la escribió la última) y la hermana que la
#: reingesta trajo a su propia fila con el órgano 111.
_SUPERVIVIENTE = "placsp:222:EXP-1"
_HERMANA = "placsp:111:EXP-1"
#: Pisada que la reingesta no alcanzó: sus hijas no se pueden juzgar.
_SIN_REINGERIR = "placsp:333:EXP-2"
#: Fila fuera del inventario.
_AJENA = "placsp:444:EXP-3"


def _sembrar(c: Any) -> None:
    for id_externo, extraida in (
        (_SUPERVIVIENTE, _DESPUES),
        (_HERMANA, _DESPUES),
        (_SIN_REINGERIR, _ANTES),
        (_AJENA, _DESPUES),
    ):
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (%s, 't', 'bulk_202610', %s)",
            (id_externo, extraida),
        )
    for nif, (id_externo, nombre, extraida) in enumerate(
        (
            (_SUPERVIVIENTE, "De la otra licitación", _ANTES),
            (_SUPERVIVIENTE, "Propia", _DESPUES),
            (_SIN_REINGERIR, "Sin juzgar", _ANTES),
            (_AJENA, "Ajena", _ANTES),
        )
    ):
        c.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, nif, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s)",
            (id_externo, nombre, f"B0000000{nif}", extraida),
        )
    lote_viejo = c.execute(
        "INSERT INTO lotes (licitacion_id, numero, fecha_extraccion) "
        "VALUES (%s, '9', %s) RETURNING id",
        (_SUPERVIVIENTE, _ANTES),
    ).fetchone()[0]
    c.execute(
        "INSERT INTO lotes (licitacion_id, numero, fecha_extraccion) VALUES (%s, '1', %s)",
        (_SUPERVIVIENTE, _DESPUES),
    )
    # Colgada de un lote que se va: tiene que irse antes que él (FK).
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, nif, lote_id, fecha_extraccion) "
        "VALUES (%s, 'Del lote viejo', 'B00000009', %s, %s)",
        (_SUPERVIVIENTE, lote_viejo, _DESPUES),
    )
    for orden, extraida in ((1, _ANTES), (2, _DESPUES)):
        c.execute(
            "INSERT INTO licitacion_garantias (licitacion_id, orden, fecha_extraccion) "
            "VALUES (%s, %s, %s)",
            (_SUPERVIVIENTE, orden, extraida),
        )
    for id_externo, uri in (
        (_SUPERVIVIENTE, "https://contrataciondelestado.es/doc/compartido.pdf"),
        (_SUPERVIVIENTE, "https://contrataciondelestado.es/doc/propio.pdf"),
        (_HERMANA, "https://contrataciondelestado.es/doc/compartido.pdf"),
        (_AJENA, "https://contrataciondelestado.es/doc/compartido.pdf"),
    ):
        c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri) VALUES (%s, 'legal', %s)",
            (id_externo, uri),
        )
    c.execute(
        "INSERT INTO follows (user_key, target_type, target_id) VALUES ('u1', 'licitacion', %s)",
        (_SUPERVIVIENTE,),
    )


def _hijas(c: Any) -> dict[str, list[str]]:
    return {
        "adjudicaciones": [
            f"{r[0]}|{r[1]}"
            for r in c.execute(
                "SELECT licitacion_id, nombre FROM adjudicaciones ORDER BY 1, 2"
            ).fetchall()
        ],
        "lotes": [r[0] for r in c.execute("SELECT numero FROM lotes ORDER BY 1").fetchall()],
        "garantias": [
            str(r[0])
            for r in c.execute("SELECT orden FROM licitacion_garantias ORDER BY 1").fetchall()
        ],
        "documentos": [
            f"{r[0]}|{r[1].rsplit('/', 1)[-1]}"
            for r in c.execute("SELECT licitacion_id, uri FROM documentos ORDER BY 1, 2").fetchall()
        ],
    }


def test_integration_limpia_solo_lo_que_la_pisada_dejo(tmp_db: Any) -> None:
    from db.database import connect, connect_read
    from db.repositories.identidad import limpiar_hijas_pisadas

    with connect() as c:
        _sembrar(c)
    with connect_read() as c:
        antes = _hijas(c)
    ids = [_SUPERVIVIENTE, _SIN_REINGERIR]

    plan = limpiar_hijas_pisadas(ids, reingesta_desde=_DESDE)
    with connect_read() as c:
        assert _hijas(c) == antes, "sin aplicar no borra nada"

    borradas = limpiar_hijas_pisadas(ids, reingesta_desde=_DESDE, aplicar=True)
    assert borradas == plan
    assert borradas == {
        "adjudicaciones": 2,
        "lotes": 1,
        "licitacion_criterios_adjudicacion": 0,
        "licitacion_garantias": 1,
        "licitacion_solvencia": 0,
        "documentos": 1,
    }
    with connect_read() as c:
        assert _hijas(c) == {
            "adjudicaciones": [
                f"{_SUPERVIVIENTE}|Propia",
                f"{_SIN_REINGERIR}|Sin juzgar",
                f"{_AJENA}|Ajena",
            ],
            "lotes": ["1"],
            "garantias": ["2"],
            "documentos": [
                f"{_HERMANA}|compartido.pdf",
                f"{_SUPERVIVIENTE}|propio.pdf",
                f"{_AJENA}|compartido.pdf",
            ],
        }
    assert limpiar_hijas_pisadas(ids, reingesta_desde=_DESDE, aplicar=True) == dict.fromkeys(
        borradas, 0
    ), "reejecutar no borra más"


def test_integration_los_datos_de_usuario_salen_con_su_hermana(tmp_db: Any) -> None:
    from db.database import connect
    from db.repositories.identidad import datos_de_usuario_en

    with connect() as c:
        _sembrar(c)
    datos = datos_de_usuario_en([_SUPERVIVIENTE, _SIN_REINGERIR])
    assert [(d["tabla"], d["id_externo"], d["hermanas"]) for d in datos] == [
        ("follows", _SUPERVIVIENTE, [_HERMANA])
    ]


def test_el_script_solo_toma_las_pisadas_seguras() -> None:
    from scripts import limpiar_hijas_pisadas_placsp as script

    inventario = [
        {"id_externo": "segura", "sim_organo": 0.1, "sim_titulo": 0.2},
        {"id_externo": "segura", "sim_organo": 0.3, "sim_titulo": 0.0},
        {"id_externo": "renombre", "sim_organo": 0.8, "sim_titulo": 0.1},
        {"id_externo": "mismo-titulo", "sim_organo": 0.1, "sim_titulo": 0.9},
    ]
    with (
        patch.object(script, "inventario_pisadas_placsp", return_value=inventario),
        patch.object(script, "limpiar_hijas_pisadas", return_value={"lotes": 0}) as limpiar,
        patch.object(script, "datos_de_usuario_en", return_value=[]),
        patch.object(script, "configure_logging"),
    ):
        assert script.main(["--desde", _DESDE, "--aplicar"]) == 0
    limpiar.assert_called_once_with(["segura"], reingesta_desde=_DESDE, aplicar=True)


def test_el_script_rechaza_una_fecha_mal_formada() -> None:
    from scripts import limpiar_hijas_pisadas_placsp as script

    with pytest.raises(ValueError):
        script.main(["--desde", "31/10/2026"])
