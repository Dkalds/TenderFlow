"""El guard de la superficie pública tiene que estar CABLEADO, no sólo escrito.

Motivación
----------
``scripts/check_public_surface.py`` es el único control automático de la
restricción dura del producto: que la superficie anónima no exponga
adjudicatarios, NIF ni analítica propietaria. Estaba escrito, pasaba limpio…
y no lo invocaba nadie — ni el Makefile, ni ``.github/workflows/ci.yml``, ni
pre-commit, ni un test. ``grep -rn check_public_surface`` sólo lo encontraba en
el propio script y en los docstrings que afirmaban que corría en CI.

Ese es el fallo que este test congela, y es de cableado, no de lógica: un gate
que nadie ejecuta es un fichero con permisos de ejecución. Por eso se comprueba
quién lo llama (target del Makefile, paso del workflow) además de que hoy pase
sobre el árbol real.

``.PHONY`` entra en la comprobación a propósito: sin él, el día que aparezca un
fichero o directorio llamado ``check-public-surface`` make daría el target por
actualizado y no ejecutaría nada — la misma clase de gate silencioso.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_ROOT = Path(__file__).resolve().parent.parent
_MAKEFILE = _ROOT / "Makefile"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_SCRIPT = "scripts/check_public_surface.py"
_TARGET = "check-public-surface"


def _lineas_phony(makefile: str) -> set[str]:
    nombres: set[str] = set()
    for linea in makefile.splitlines():
        if linea.startswith(".PHONY:"):
            nombres.update(linea.removeprefix(".PHONY:").split())
    return nombres


def _pasos_run(workflow: dict) -> list[str]:
    """Todos los ``run:`` del workflow, de cualquier job."""
    comandos: list[str] = []
    for job in workflow.get("jobs", {}).values():
        for paso in job.get("steps", []) or []:
            if isinstance(paso, dict) and isinstance(paso.get("run"), str):
                comandos.append(paso["run"])
    return comandos


def test_el_script_existe() -> None:
    assert (_ROOT / _SCRIPT).is_file(), f"{_SCRIPT} desapareció: el resto del test no dice nada"


def test_makefile_expone_el_target() -> None:
    makefile = _MAKEFILE.read_text(encoding="utf-8")
    receta = re.search(rf"^{re.escape(_TARGET)}:.*?##.*?\n((?:\t.*\n)+)", makefile, re.MULTILINE)
    assert receta, f"Makefile sin target '{_TARGET}' (con su comentario '##' de ayuda)"
    assert _SCRIPT in receta.group(1), f"El target '{_TARGET}' no invoca {_SCRIPT}"


def test_el_target_esta_en_phony() -> None:
    assert _TARGET in _lineas_phony(_MAKEFILE.read_text(encoding="utf-8")), (
        f"'{_TARGET}' falta en .PHONY: un fichero homónimo lo dejaría sin ejecutar"
    )


def test_ci_ejecuta_el_guard() -> None:
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    comandos = _pasos_run(workflow)
    invocaciones = [c for c in comandos if _SCRIPT in c]
    assert invocaciones, f"ci.yml no ejecuta {_SCRIPT} en ningún job"
    # `--strict` o el guard informa y sale 0: el modo aviso es el estado del
    # que venimos, y es indistinguible de no tener gate.
    assert any("--strict" in c for c in invocaciones), (
        f"ci.yml invoca {_SCRIPT} sin --strict: informaría del hallazgo sin fallar"
    )


def test_el_guard_pasa_sobre_el_arbol_actual() -> None:
    """Mismo cálculo que hará CI, en proceso: hoy el árbol está limpio.

    Que el gate quede cableado no sirve de nada si entra en rojo el mismo día;
    esto lo detecta aquí y no en el primer PR ajeno que pase por delante.
    """
    from scripts import check_public_surface as guard

    hallazgos = [h for ruta in guard._ficheros() for h in guard._escanear(ruta)]
    assert not hallazgos, "\n".join(
        f"{h.categoria} {h.fichero}:{h.linea} {h.texto}" for h in hallazgos
    )
