"""La política de retención es configuración publicada, no literales (C9.3).

Antes de este ítem los plazos vivían en tres sitios que podían divergir sin que
nada fallara: los argumentos por defecto de `run_retention`, los `--*-days` del
CLI y el job programado. Ninguno de los tres aparecía en `docs/SECURITY.md`.

Lo que estos tests protegen:

1. Que no vuelva a aparecer un plazo literal en `scheduler/retention.py`.
2. Que el job, el CLI y la política apliquen los mismos números.
3. Que el documento publicado no se separe del código que purga.
4. Que toda tabla purgada tenga fila en la política, y al revés.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from config.settings import settings
from scheduler.retention import COLUMNA_FECHA, POLITICA_RETENCION, ReglaRetencion

ROOT = Path(__file__).resolve().parent.parent
RETENTION_PY = ROOT / "scheduler" / "retention.py"

# Enteros que no son plazos: índices, factores y centinelas. Cualquier otro
# número en este módulo es sospechoso de ser un plazo escondido.
_ENTEROS_PERMITIDOS = frozenset({0, 1, -1, 2, 30})


def test_sin_plazos_literales_en_retention() -> None:
    """Ningún literal numérico grande en `scheduler/retention.py`.

    `30` se permite porque es el factor meses→días de `ReglaRetencion`, no un
    plazo; `0`, `1`, `-1` y `2` son centinelas e índices.
    """
    arbol = ast.parse(RETENTION_PY.read_text(encoding="utf-8"))
    sospechosos = [
        nodo.value
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Constant)
        and isinstance(nodo.value, int)
        and not isinstance(nodo.value, bool)
        and nodo.value not in _ENTEROS_PERMITIDOS
    ]
    assert not sospechosos, (
        "scheduler/retention.py contiene enteros que parecen plazos: "
        f"{sorted(set(sospechosos))}. Los plazos van en RETENTION_* "
        "(config/settings.py) y se declaran en POLITICA_RETENCION."
    )


def test_toda_tabla_purgada_tiene_politica() -> None:
    """`COLUMNA_FECHA` y `POLITICA_RETENCION` describen el mismo conjunto.

    Una tabla que se purga sin fila en la política se purgaría sin aparecer en
    `docs/SECURITY.md`; una fila sin tabla publicaría un plazo que nadie aplica.
    """
    en_politica = {r.tabla for r in POLITICA_RETENCION}
    purgadas_por_plazo = set(COLUMNA_FECHA)
    # `failed_extractions` y `rate_limits` se purgan por camino propio (DLQ
    # resueltos y ventanas expiradas), así que no están en COLUMNA_FECHA.
    solo_camino_propio = {"failed_extractions", "rate_limits"}

    assert purgadas_por_plazo - en_politica == set(), (
        "tablas purgadas sin fila en POLITICA_RETENCION: " f"{purgadas_por_plazo - en_politica}"
    )
    assert en_politica - purgadas_por_plazo == solo_camino_propio, (
        "POLITICA_RETENCION declara tablas que nadie purga: "
        f"{en_politica - purgadas_por_plazo - solo_camino_propio}"
    )


@pytest.mark.parametrize("regla", POLITICA_RETENCION, ids=lambda r: r.tabla)
def test_cada_regla_apunta_a_un_ajuste_real(regla: ReglaRetencion) -> None:
    assert regla.ajuste.startswith("RETENTION_"), f"{regla.ajuste} no es un ajuste de retención"
    assert hasattr(settings, regla.ajuste), f"{regla.ajuste} no existe en config/settings.py"
    assert regla.dias >= 0


def test_documento_de_retencion_al_dia() -> None:
    """`docs/SECURITY.md` publica exactamente lo que el código aplica."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_retention_doc.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "docs/SECURITY.md tiene la política de retención desfasada. "
        f"Regenerá con `python scripts/gen_retention_doc.py`.\n{proc.stderr}"
    )


def test_env_example_documenta_los_plazos() -> None:
    texto = (ROOT / ".env.example").read_text(encoding="utf-8")
    faltan = [
        nombre
        for nombre in type(settings).model_fields
        if nombre.startswith("RETENTION_") and nombre not in texto
    ]
    assert not faltan, f"RETENTION_* sin documentar en .env.example: {faltan}"


def test_plazo_negativo_se_rechaza() -> None:
    """Un typo en una variable de entorno no puede abrir un `DELETE` sin cota."""
    from config.settings import Settings

    with pytest.raises(ValueError, match="retenci"):
        Settings(RETENTION_AUDIT_LOG_DAYS=-1)  # type: ignore[call-arg]
