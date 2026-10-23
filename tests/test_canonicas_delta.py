"""La medición del delta de ``v156`` compara exactamente los dos criterios de la vista.

Si ``orden_v102_sql`` no reprodujera el orden congelado en ``v102``, el número que
revisa el propietario antes de migrar describiría un cambio que no es el que va
a aplicar. Con base, que cuenta los contratos que cambian de fila y solo esos.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from db.database import connect
from db.repositories.canonicas_delta import (
    CambioCanonica,
    DeltaCanonicas,
    medir_delta,
    orden_v102_sql,
)

_RAIZ = Path(__file__).resolve().parents[1]


def _cargar(ruta: Path, nombre: str) -> Any:
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(nombre, modulo)
    spec.loader.exec_module(modulo)
    return modulo


def test_el_orden_viejo_es_el_congelado_en_v102() -> None:
    v102 = _cargar(
        _RAIZ / "db" / "alembic" / "versions" / "v102_mv_canonicas_clave_inmutable.py",
        "v102_mv_canonicas_clave_inmutable",
    )
    assert v102._CUERPO.endswith(orden_v102_sql())


def test_el_resumen_agrupa_por_transicion() -> None:
    script = _cargar(_RAIZ / "scripts" / "medir_delta_canonicas.py", "medir_delta_canonicas")
    delta = DeltaCanonicas(
        contratos=200,
        cambios=[
            CambioCanonica("ted:1", "ted", "EXP-1", "bulk_202606"),
            CambioCanonica("ted:2", "ted", "EXP-2", "bulk_202606"),
            CambioCanonica("EXP-3", "placsp", "EXP-3B", "bulk_202605"),
        ],
    )
    texto = script.render_texto(delta, limite=1)

    assert "Cambian de fila canónica: 3 (1.50 %)" in texto
    assert "ted → bulk_202606: 2" in texto
    assert "Ejemplos (1 de 3)" in texto


def _gemelas(c: Any, sufijo: str, filas: list[tuple[str, str, str]]) -> None:
    for id_externo, fuente, fecha in filas:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, organo_contratacion, cpv, "
            "importe, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, '72000000', 1000, %s, '2026-07-01T00:00:00+00:00')",
            (
                id_externo,
                f"Servicio de mantenimiento de la plataforma {sufijo} municipal",
                fuente,
                f"Ayuntamiento {sufijo}",
                fecha,
            ),
        )


def test_cuenta_solo_los_contratos_que_cambian_de_fila(tmp_db) -> None:
    with connect() as c:
        _gemelas(c, "A", [("ted:A", "ted", "2026-03-01"), ("pscp:A", "pscp", "2026-03-20")])
        _gemelas(c, "B", [("EXP-B", "bulk_202603", "2026-03-25"), ("pscp:B", "pscp", "2026-03-02")])
        # Sin cambio: PLACSP ya ganaba con v102.
        _gemelas(c, "C", [("EXP-C", "placsp", "2026-03-25"), ("ted:C", "ted", "2026-03-02")])
        _gemelas(c, "D", [("pscp:D", "pscp", "2026-03-02")])

    delta = medir_delta()

    assert delta.contratos == 4
    assert {(x.antes, x.despues) for x in delta.cambios} == {
        ("ted:A", "pscp:A"),
        ("pscp:B", "EXP-B"),
    }
