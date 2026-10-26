"""``scripts/run_gates.py``: la lista de gates está completa y no corta en el primero.

El riesgo de agrupar los gates en un paso es dejarse uno fuera sin que nadie lo
note. Estos tests lo cierran: todo ``scripts/check_*.py`` está clasificado en
exactamente un grupo, y el grupo ``stdlib`` de verdad no importa nada de fuera
de la biblioteca estándar (es lo que promete ``make gates`` en un checkout sin
``.venv``). No ejecutan los gates: eso es ``make gates``.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "run_gates.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("run_gates", _SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["run_gates"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture()
def gates():
    return _cargar()


def _clasificados(gates) -> list[str]:
    return [
        *(g.script for g in gates.STDLIB),
        *(g.script for g in gates.DEPS if g.script.startswith("check_")),
        *gates.FUERA,
    ]


def test_todo_check_esta_en_un_grupo_y_solo_en_uno(gates):
    """Un gate nuevo sin clasificar falla aquí: o corre en un grupo o dice por qué no."""
    en_disco = sorted(p.name for p in (_ROOT / "scripts").glob("check_*.py"))
    clasificados = _clasificados(gates)

    assert sorted(clasificados) == en_disco, (
        "Clasificá cada scripts/check_*.py en STDLIB, DEPS o FUERA (con motivo) "
        "de scripts/run_gates.py."
    )
    assert len(clasificados) == len(set(clasificados))


def test_los_scripts_citados_existen(gates):
    for gate in (*gates.STDLIB, *gates.DEPS):
        assert (_ROOT / "scripts" / gate.script).is_file(), gate.script


def _imports_de_fuera(path: Path) -> set[str]:
    """Módulos de primer nivel que no son de la stdlib, incluidos imports perezosos."""
    arbol = ast.parse(path.read_text(encoding="utf-8"))
    modulos: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos |= {alias.name.split(".")[0] for alias in nodo.names}
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            modulos.add(nodo.module.split(".")[0])
    return {m for m in modulos if m not in sys.stdlib_module_names and m != "__future__"}


def test_el_grupo_stdlib_no_importa_nada_de_fuera(gates):
    """``make gates`` corre sin ``.venv``: un import de la app lo mueve a DEPS."""
    culpables = {
        g.script: sorted(fuera)
        for g in gates.STDLIB
        if (fuera := _imports_de_fuera(_ROOT / "scripts" / g.script))
    }

    assert culpables == {}


def test_no_corta_en_el_primer_fallo_y_resume_todos(gates, monkeypatch, capsys):
    llamadas: list[list[str]] = []
    codigos = iter([0, 1, 0])

    def falso_run(argv, **_kwargs):
        llamadas.append(argv)
        return SimpleNamespace(returncode=next(codigos))

    trio = (gates.Gate("check_a.py"), gates.Gate("check_b.py"), gates.Gate("check_c.py"))
    monkeypatch.setattr(gates.subprocess, "run", falso_run)
    monkeypatch.setattr(gates, "STDLIB", trio)

    assert gates.main([]) == 1
    assert [Path(argv[1]).name for argv in llamadas] == ["check_a.py", "check_b.py", "check_c.py"]
    salida = capsys.readouterr()
    assert "FALLA (exit 1)  check_b.py" in salida.out
    assert "1 de 3 gates fallaron" in salida.err


def test_todo_en_verde_sale_con_cero(gates, monkeypatch):
    monkeypatch.setattr(gates.subprocess, "run", lambda argv, **_: SimpleNamespace(returncode=0))
    monkeypatch.setattr(gates, "STDLIB", (gates.Gate("check_a.py"),))

    assert gates.main([]) == 0


def test_el_esquema_openapi_se_comparte_entre_los_gates_de_contrato(gates, monkeypatch):
    rutas: list[str] = []

    def falso_run(argv, **_kwargs):
        rutas.extend(a for a in argv if a.endswith("openapi.json"))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gates.subprocess, "run", falso_run)
    deps_openapi = tuple(g for g in gates.DEPS if gates.OPENAPI in g.args)
    monkeypatch.setattr(gates, "DEPS", deps_openapi)

    assert gates.main(["--deps"]) == 0
    assert len(rutas) == len(deps_openapi) == 3
    assert len(set(rutas)) == 1
    assert gates.OPENAPI not in rutas


def test_el_playbook_lleva_la_tabla_al_dia(gates):
    """La copia de docs/AGENT_PLAYBOOK.md §2 es la salida de ``--list``."""
    playbook = (_ROOT / "docs" / "AGENT_PLAYBOOK.md").read_text(encoding="utf-8")
    inicio, fin = "<!-- run_gates:inicio -->\n", "\n<!-- run_gates:fin -->"
    copia = playbook[playbook.index(inicio) + len(inicio) : playbook.index(fin)]

    assert copia == gates.tabla(), (
        "Regenerá la tabla de docs/AGENT_PLAYBOOK.md con python scripts/run_gates.py --list"
    )


def test_el_makefile_expone_los_dos_grupos():
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "\ngates:" in makefile
    assert "python scripts/run_gates.py\n" in makefile
    assert "\ngates-deps:" in makefile
    assert "python scripts/run_gates.py --deps" in makefile
