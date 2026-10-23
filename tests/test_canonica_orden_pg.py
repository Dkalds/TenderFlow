"""El orden de canónica, ejecutado: el SQL y su gemelo Python eligen la misma fila.

``tests/test_dedupe_publico.py`` compara los dos criterios como texto y prueba
el gemelo Python con filas sueltas. Eso no ve la clase de deriva que solo
aparece al ejecutar —un ``LIKE`` cuyo ``_`` actúa de comodín, un ``NULL`` que
Postgres ordena al final y Python no—, así que aquí se ordena el mismo conjunto
de filas en Postgres y en Python y se exige el mismo resultado. Y, de punta a
punta, que la vista materializada de la revisión vigente (``v156``) se queda con
la fila que dice el criterio: la de PLACSP aunque la haya refrescado el bulk, y
nunca la de TED si hay otra.
"""

from __future__ import annotations

from typing import Any

from db.database import connect
from db.repositories.publico import refrescar_vista_canonicas
from db.sql_fragments import orden_canonico_sql
from services.dedupe import _rango_canonico

# Mezcla las tres franjas del criterio y, dentro de cada una, los desempates por
# fecha de publicación, primera extracción e id. `bulkx` no es del carril bulk.
_FILAS: list[dict[str, Any]] = [
    {"id_externo": "ted:1", "fuente": "ted", "fecha_publicacion": "2020-01-01"},
    {"id_externo": "ted:0", "fuente": "ted", "fecha_publicacion": "2020-01-01"},
    {"id_externo": "pscp:B", "fuente": "pscp", "fecha_publicacion": "2026-05-01"},
    {"id_externo": "pscp:A", "fuente": "pscp", "fecha_publicacion": None},
    {"id_externo": "gal:1", "fuente": "galicia_rss", "fecha_publicacion": "2024-01-01"},
    {"id_externo": "raro:1", "fuente": "bulkx", "fecha_publicacion": "2021-01-01"},
    {"id_externo": "EXP-2", "fuente": "bulk_202606", "fecha_publicacion": "2026-06-01"},
    {"id_externo": "EXP-1", "fuente": "placsp", "fecha_publicacion": "2026-06-01"},
    {
        "id_externo": "EXP-0",
        "fuente": "placsp",
        "fecha_publicacion": None,
        "primera_extraccion": "2026-01-01T00:00:00+00:00",
    },
]


def _insertar(c: Any, fila: dict[str, Any], **extra: Any) -> None:
    campos = {
        "titulo": "Suministro de licencias de software para el ayuntamiento",
        "fecha_extraccion": "2026-07-01T00:00:00+00:00",
        "primera_extraccion": None,
        **fila,
        **extra,
    }
    columnas = ", ".join(campos)
    marcas = ", ".join(["%s"] * len(campos))
    c.execute(f"INSERT INTO licitaciones ({columnas}) VALUES ({marcas})", list(campos.values()))  # noqa: S608 -- columnas fijas del test


def test_postgres_y_python_ordenan_igual(tmp_db) -> None:
    with connect() as c:
        for fila in _FILAS:
            _insertar(c, fila)
        en_sql = [
            str(r[0])
            for r in c.execute(
                f"SELECT l.id_externo FROM licitaciones l ORDER BY {orden_canonico_sql('l')}"  # noqa: S608 -- fragmento constante
            ).fetchall()
        ]
    en_python = [
        str(f["id_externo"])
        for f in sorted(
            ({**f, "fecha_extraccion": "2026-07-01T00:00:00+00:00"} for f in _FILAS),
            key=_rango_canonico,
        )
    ]

    assert en_sql == en_python
    assert en_sql[:3] == ["EXP-1", "EXP-2", "EXP-0"]
    assert en_sql[-2:] == ["ted:0", "ted:1"]


def _gemelas(c: Any, sufijo: str, filas: list[tuple[str, str, str]]) -> None:
    """Filas que colapsan por clave: mismo órgano, CPV4, año-mes y título."""
    for id_externo, fuente, fecha in filas:
        _insertar(
            c,
            {"id_externo": id_externo, "fuente": fuente, "fecha_publicacion": fecha},
            titulo=f"Servicio de mantenimiento de la plataforma {sufijo} municipal",
            organo_contratacion=f"Ayuntamiento {sufijo}",
            cpv="72000000",
            importe=100000.0,
        )


def test_la_vista_no_elige_ted_y_cuenta_el_bulk_como_placsp(tmp_db) -> None:
    with connect() as c:
        # TED publicó antes: con el criterio de v102 ganaba por antigüedad.
        _gemelas(c, "A", [("ted:A", "ted", "2026-03-01"), ("pscp:A", "pscp", "2026-03-20")])
        # El bulk refrescó la fila de PLACSP: con v102 perdía frente a PSCP.
        _gemelas(c, "B", [("EXP-B", "bulk_202603", "2026-03-25"), ("pscp:B", "pscp", "2026-03-02")])

    refrescar_vista_canonicas()

    with connect() as c:
        en_vista = {
            str(r[0]) for r in c.execute("SELECT id_externo FROM licitaciones_canonicas").fetchall()
        }
    assert en_vista == {"pscp:A", "EXP-B"}
