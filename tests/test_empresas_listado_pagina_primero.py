"""``list_empresas`` por nombre o NIF corta la página antes de agregar.

Hasta 2026-11 cada página del buscador del maestro hacía ``LEFT JOIN
adjudicaciones`` + ``GROUP BY`` sobre todas las empresas para quedarse con
``limit`` filas. Con los órdenes que no dependen del agregado, ahora se pagina
``empresas`` y solo esas filas se agregan. Estos tests fijan que el resultado
es **exactamente** el de la consulta anterior (filas, agregados y orden, con
empates, NIF ausentes, búsqueda y desplazamientos) y que el plan ya no agrupa
el maestro.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

import pytest

#: La consulta de antes, copiada tal cual: es la referencia de la equivalencia.
_REFERENCIA = (
    "SELECT e.empresa_id, e.nombre_canonico, e.nif_canonico, e.es_ute, e.es_pyme, "
    "       g.nombre AS grupo, "
    "       COUNT(a.id) AS n_adjudicaciones, "
    "       COALESCE(SUM(a.importe_adjudicado), 0) AS importe_total "
    "FROM empresas e "
    "LEFT JOIN grupos_empresariales g ON g.grupo_id = e.grupo_id "
    "LEFT JOIN adjudicaciones a ON a.empresa_id = e.empresa_id "
    "{where}"
    "GROUP BY e.empresa_id, e.nombre_canonico, e.nif_canonico, e.es_ute, e.es_pyme, g.nombre "
    "ORDER BY {expr} {dir} NULLS LAST, e.empresa_id ASC "
    "LIMIT %s OFFSET %s"
)
_WHERE_Q = (
    "WHERE e.nombre_canonico LIKE %s OR e.nif_canonico LIKE %s "
    "OR e.empresa_id IN "
    "(SELECT empresa_id FROM empresa_aliases WHERE alias_normalizado LIKE %s) "
)
_EXPR = {"nombre": "LOWER(e.nombre_canonico)", "nif": "e.nif_canonico"}


@pytest.fixture()
def maestro(tmp_db: Any) -> None:
    """Empates por nombre en minúsculas, NIF ausentes, empresas sin adjudicaciones,
    grupos y un alias que solo casa por la tabla de aliases."""
    from db.database import connect

    with connect() as c:
        grupo = c.execute(
            "INSERT INTO grupos_empresariales (nombre) VALUES ('Grupo Uno') RETURNING grupo_id"
        ).fetchone()[0]
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_publicacion, fecha_extraccion) "
            "VALUES ('LIC-1', 'Prueba', '2026-01-15', CURRENT_TIMESTAMP)"
        )
        filas = [
            # (nombre, nif, grupo?, importes de sus adjudicaciones)
            ("ACME SISTEMAS", "B0000001", True, [100.0, 50.0]),
            ("acme sistemas", None, False, [10.0]),
            ("Acme Sistemas", "B0000003", False, []),
            ("Beta Redes", None, True, [None, 5.0]),
            ("CIRCULO DATOS", "B0000005", False, [7.5]),
            ("delta ute", "U0000006", False, []),
            ("Épsilon Software", None, False, [1.0, 2.0, 3.0]),
            ("ZETA CLOUD", "B0000008", True, [999.0]),
            ("eta", "B0000009", False, [0.0]),
            ("Theta Consultores", None, False, []),
        ]
        for i, (nombre, nif, con_grupo, importes) in enumerate(filas):
            empresa_id = c.execute(
                "INSERT INTO empresas (nombre_canonico, nif_canonico, grupo_id, es_ute, es_pyme) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING empresa_id",
                (nombre, nif, grupo if con_grupo else None, int(i % 3 == 0), int(i % 2 == 0)),
            ).fetchone()[0]
            for importe in importes:
                c.execute(
                    "INSERT INTO adjudicaciones "
                    "(licitacion_id, nombre, importe_adjudicado, empresa_id, fecha_extraccion) "
                    "VALUES ('LIC-1', %s, %s, %s, CURRENT_TIMESTAMP)",
                    (nombre, importe, empresa_id),
                )
            if nombre == "Theta Consultores":
                c.execute(
                    "INSERT INTO empresa_aliases (empresa_id, alias_normalizado) VALUES (%s, %s)",
                    (empresa_id, "ACME ANTIGUA"),
                )


def _referencia(q: str | None, sort: str, order: str, limit: int, offset: int) -> list[dict]:
    from db.database import connect_read
    from db.repositories.base import rows_to_dicts

    params: list[object] = []
    if q:
        like = f"%{q.upper()}%"
        params = [like, like, like]
    sql = _REFERENCIA.format(
        where=_WHERE_Q if q else "", expr=_EXPR[sort], dir="ASC" if order == "asc" else "DESC"
    )
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, [*params, limit, offset]))


@pytest.mark.parametrize(
    ("q", "sort", "order", "limit", "offset"),
    [
        (q, sort, order, limit, offset)
        for q, sort, order, (limit, offset) in itertools.product(
            [None, "acme", "s"],
            ["nombre", "nif"],
            ["asc", "desc"],
            [(3, 0), (3, 3), (4, 7), (50, 0), (5, 40)],
        )
    ],
)
def test_misma_pagina_que_la_consulta_que_agrupaba_todo(
    maestro: None, q: str | None, sort: Any, order: Any, limit: int, offset: int
) -> None:
    from db.repositories.empresas import EmpresasReadRepository

    filas, _total = EmpresasReadRepository().list_empresas(q, limit, offset, sort, order)

    assert filas == _referencia(q, sort, order, limit, offset)


def test_por_nombre_no_agrupa_el_maestro_entero(maestro: None, monkeypatch: Any) -> None:
    """El plan agrega por empresa de la página, no con un ``GROUP BY`` de todas."""
    import db.repositories.empresas as modulo
    from db.database import connect_read

    consultas: list[str] = []
    original = modulo.connect_read

    class _Espia:
        def __init__(self, conexion: Any) -> None:
            self._c = conexion

        def execute(self, sql: str, params: Any = None) -> Any:
            consultas.append(sql)
            return self._c.execute(sql, params)

    class _Ctx:
        def __enter__(self) -> _Espia:
            self._cm = original()
            return _Espia(self._cm.__enter__())

        def __exit__(self, *exc: object) -> None:
            self._cm.__exit__(*exc)

    monkeypatch.setattr(modulo, "connect_read", _Ctx)
    modulo.EmpresasReadRepository().list_empresas(None, 3, 0, "nombre", "asc")

    pagina = consultas[0]
    with connect_read() as c:
        plan = json.dumps(c.execute("EXPLAIN (FORMAT JSON) " + pagina, [3, 0]).fetchone()[0])
    assert '"Group Key"' not in plan
