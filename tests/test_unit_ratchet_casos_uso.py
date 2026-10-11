"""Trazabilidad de los casos de uso (``scripts/check_casos_uso.py``).

Un caso del catálogo necesita un recorrido —escenario por la API o E2E— y un
test no puede citar un caso que no existe. El primer test corre el gate de
verdad sobre el repo; el resto mueven una pieza cada uno sobre un árbol mínimo.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "check_casos_uso.py"


def _cargar_modulo():
    spec = importlib.util.spec_from_file_location("check_casos_uso", _SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["check_casos_uso"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture()
def gate():
    return _cargar_modulo()


_CATALOGO_MINIMO = """# Casos de uso

### CU-90 — Hacer una cosa

### CU-91 — Hacer otra

## Trazabilidad

{inicio}

{fin}
"""


@pytest.fixture()
def arbol(gate, tmp_path, monkeypatch):
    """Un repo de dos casos, cada uno con su recorrido, y la tabla al día."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "web" / "e2e").mkdir(parents=True)
    catalogo = tmp_path / "docs" / "casos-de-uso.md"
    catalogo.write_text(
        _CATALOGO_MINIMO.format(inicio=gate._INICIO, fin=gate._FIN), encoding="utf-8"
    )
    (tmp_path / "tests" / "test_escenario_cosa.py").write_text(
        'def test_una_cosa():\n    """CU-90 — de punta a punta."""\n', encoding="utf-8"
    )
    (tmp_path / "web" / "e2e" / "otra.spec.ts").write_text(
        'test("hace otra", async () => {\n  // CU-91\n});\n', encoding="utf-8"
    )
    monkeypatch.setattr(gate, "_ROOT", tmp_path)
    monkeypatch.setattr(gate, "_CATALOGO", catalogo)
    monkeypatch.setattr(gate, "SIN_RECORRIDO", {})
    assert gate.main(["--write"]) == 0
    return tmp_path


def _calcular(gate, arbol):
    return gate.calcular(arbol, arbol / "docs" / "casos-de-uso.md")


def test_el_catalogo_de_hoy_pasa_el_gate(gate, capsys):
    """El check corrido de verdad sobre el repo: es lo que vigila CI."""
    assert gate.main([]) == 0, capsys.readouterr().err
    assert "Casos de uso OK" in capsys.readouterr().out


def test_las_excepciones_reales_llevan_motivo(gate):
    cortos = [
        caso
        for caso, motivo in gate.SIN_RECORRIDO.items()
        if len(motivo.strip()) < gate.MOTIVO_MINIMO
    ]
    assert cortos == []


def test_pasa_con_cada_caso_recorrido_y_la_tabla_al_dia(gate, arbol, capsys):
    assert gate.main([]) == 0
    assert "2 casos, 2 con recorrido" in capsys.readouterr().out


def test_un_caso_sin_recorrido_falla(gate, arbol, capsys):
    (arbol / "web" / "e2e" / "otra.spec.ts").unlink()

    assert gate.main([]) == 1
    error = capsys.readouterr().err
    assert "CU-91" in error
    assert "no tiene ningún recorrido" in error


def test_un_test_de_una_sola_ruta_no_cuenta_como_recorrido(gate, arbol, capsys):
    """Citar el caso desde un test cualquiera lo lista, pero no lo recorre."""
    (arbol / "web" / "e2e" / "otra.spec.ts").unlink()
    (arbol / "tests" / "test_ruta_suelta.py").write_text(
        'def test_responde():\n    """CU-91"""\n', encoding="utf-8"
    )

    estado, _ = _calcular(gate, arbol)
    assert [c.ruta for c in estado.citas["CU-91"]] == ["tests/test_ruta_suelta.py"]
    assert estado.recorridos("CU-91") == []
    assert gate.main([]) == 1


def test_una_excepcion_con_motivo_deja_pasar_el_caso(gate, arbol, monkeypatch):
    (arbol / "web" / "e2e" / "otra.spec.ts").unlink()
    monkeypatch.setattr(
        gate,
        "SIN_RECORRIDO",
        {"CU-91": "Depende de un servicio externo que la suite no puede levantar todavía."},
    )

    assert gate.main(["--write"]) == 0
    assert gate.main([]) == 0


def test_un_motivo_de_compromiso_no_vale(gate, arbol, monkeypatch, capsys):
    (arbol / "web" / "e2e" / "otra.spec.ts").unlink()
    monkeypatch.setattr(gate, "SIN_RECORRIDO", {"CU-91": "pendiente"})

    assert gate.main(["--write"]) == 1
    assert "no dice qué impide" in capsys.readouterr().err


def test_la_excepcion_de_un_caso_ya_recorrido_sobra(gate, arbol, monkeypatch, capsys):
    """Así la lista solo encoge: quien añade el recorrido borra la entrada."""
    monkeypatch.setattr(
        gate, "SIN_RECORRIDO", {"CU-90": "Ya no aplica, pero nadie borró esta línea del script."}
    )

    assert gate.main([]) == 1
    assert "solo puede encoger" in capsys.readouterr().err


def test_citar_un_caso_que_no_existe_falla(gate, arbol, capsys):
    """Una errata, o un caso retirado que un test sigue diciendo que cubre."""
    (arbol / "tests" / "test_escenario_cosa.py").write_text(
        'def test_una_cosa():\n    """CU-90 y CU-99."""\n', encoding="utf-8"
    )

    assert gate.main([]) == 1
    error = capsys.readouterr().err
    assert "CU-99" in error
    assert "tests/test_escenario_cosa.py" in error


def test_un_caso_declarado_dos_veces_falla(gate, arbol, capsys):
    catalogo = arbol / "docs" / "casos-de-uso.md"
    catalogo.write_text(
        catalogo.read_text(encoding="utf-8").replace(
            "### CU-91 — Hacer otra", "### CU-91 — Hacer otra\n\n### CU-91 — Repetido"
        ),
        encoding="utf-8",
    )

    assert gate.main([]) == 1
    assert "dos veces" in capsys.readouterr().err


def test_la_tabla_desfasada_falla_y_write_la_arregla(gate, arbol, capsys):
    (arbol / "tests" / "test_escenario_nuevo.py").write_text(
        'def test_otro_camino():\n    """CU-90"""\n', encoding="utf-8"
    )

    assert gate.main([]) == 1
    assert "make casos-uso" in capsys.readouterr().err
    assert gate.main(["--write"]) == 0
    assert gate.main([]) == 0
    assert "test_escenario_nuevo.py" in (arbol / "docs" / "casos-de-uso.md").read_text("utf-8")


def test_la_cita_cuenta_tests_y_distingue_el_fichero_entero(gate):
    texto = (
        '"""Fichero que recorre CU-90 entero."""\n'
        "def test_a():\n"
        '    """CU-91"""\n'
        "def test_b():\n"
        "    # CU-91 otra vez, y de nuevo CU-91 en el mismo test\n"
    )

    citas = gate.citas_de(texto, "tests/test_escenario_x.py")

    assert citas["CU-90"].fichero_entero is True
    assert citas["CU-90"].tests == 0
    assert citas["CU-91"].fichero_entero is False
    assert citas["CU-91"].tests == 2
    assert citas["CU-91"].nivel == "escenario"


def test_un_comentario_encima_del_test_se_atribuye_al_anterior(gate):
    """Por eso la cita va dentro del test: encima, cuenta para el que no es."""
    texto = 'test("uno", async () => {\n});\n// CU-90\ntest("dos", async () => {\n});\n'

    citas = gate.citas_de(texto, "web/e2e/x.spec.ts")

    assert citas["CU-90"].tests == 1
    assert citas["CU-90"].nivel == "e2e"
