"""El plazo de conservación publicado y el que aplica el job son el mismo.

El aviso legal anuncia al visitante, en el momento de recoger su correo, cuánto
tiempo se conserva su solicitud. Eso es una obligación del RGPD (art. 13), no
una nota informativa: si el número de la página y el del job se separan, el
aviso pasa a ser una promesa falsa y no falla nada — ni un test, ni un lint, ni
el propio job, que seguiría borrando con toda corrección por otro plazo.

Este fichero es la costura entre los dos lenguajes, igual que
`test_clave_canonica_index.py` lo es entre la migración y su gemela en Python.
"""

from __future__ import annotations

import re
from pathlib import Path

from scheduler.retention import (
    SOLICITUDES_ACCESO_RETENTION_DAYS,
    SOLICITUDES_ACCESO_RETENTION_MESES,
)

_LEGAL_TS = Path(__file__).resolve().parent.parent / "web" / "src" / "lib" / "legal.ts"


def _meses_publicados() -> int:
    fuente = _LEGAL_TS.read_text(encoding="utf-8")
    match = re.search(
        r"LEGAL_MESES_RETENCION_SOLICITUDES\s*=\s*(\d+)",
        fuente,
    )
    assert match, "web/src/lib/legal.ts ya no declara LEGAL_MESES_RETENCION_SOLICITUDES"
    return int(match.group(1))


def test_el_plazo_publicado_es_el_que_aplica_el_job():
    assert _meses_publicados() == SOLICITUDES_ACCESO_RETENTION_MESES


def test_los_dias_del_job_derivan_de_los_meses_publicados():
    # Si alguien fija los días a mano, el aviso y el borrado se separan sin que
    # el test de arriba lo note.
    assert SOLICITUDES_ACCESO_RETENTION_DAYS == SOLICITUDES_ACCESO_RETENTION_MESES * 30


def test_solicitudes_acceso_esta_en_la_politica_de_retencion():
    """Sin esta regla el aviso prometería un borrado que nadie ejecuta."""
    import inspect

    from scheduler import retention

    fuente = inspect.getsource(retention.run_retention)
    assert '("solicitudes_acceso", "created_at"' in fuente
