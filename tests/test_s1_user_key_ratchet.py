"""Ratchet de ``user_key`` (D18, fase 1).

Comprueba las tres propiedades que lo hacen un ratchet y no un contador: pasa
sobre el árbol de hoy, falla ante un fichero nuevo, y falla también cuando la
lista congelada conserva un fósil (si no, el número dejaría de medir la deuda
real y nadie se enteraría).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "check_user_key_ratchet.py"


def _cargar_modulo():
    spec = importlib.util.spec_from_file_location("check_user_key_ratchet", _SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["check_user_key_ratchet"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture()
def ratchet():
    return _cargar_modulo()


def test_la_lista_congelada_no_tiene_fosiles(ratchet):
    """Cada entrada sigue nombrando `user_key`; si no, el conteo mentiría.

    Se comprueba contra el árbol de verdad (no contra una lista simulada): una
    whitelist que solo puede encoger tiene que describir el repo, y ese es el
    único modo de fallo que un test con datos inventados no vería.
    """
    fosiles = sorted(ratchet.CONGELADOS - set(ratchet._ficheros_con_user_key()))

    assert fosiles == []


def test_pasa_cuando_el_arbol_es_exactamente_la_lista(ratchet, monkeypatch, capsys):
    monkeypatch.setattr(ratchet, "_ficheros_con_user_key", lambda: sorted(ratchet.CONGELADOS))

    assert ratchet.main([]) == 0
    assert "ninguno nuevo" in capsys.readouterr().out


def test_falla_ante_un_fichero_nuevo_con_user_key(ratchet, monkeypatch, capsys):
    monkeypatch.setattr(
        ratchet,
        "_ficheros_con_user_key",
        lambda: sorted({*ratchet.CONGELADOS, "api/routes/inventado.py"}),
    )

    assert ratchet.main([]) == 1
    assert "api/routes/inventado.py" in capsys.readouterr().err


def test_falla_si_la_lista_conserva_un_fosil(ratchet, monkeypatch, capsys):
    """Una whitelist que no encoge miente sobre el tamaño de la deuda."""
    quedan = sorted(ratchet.CONGELADOS)[1:]
    monkeypatch.setattr(ratchet, "_ficheros_con_user_key", lambda: quedan)

    assert ratchet.main([]) == 1
    assert sorted(ratchet.CONGELADOS)[0] in capsys.readouterr().err


def test_no_cuenta_tests_ni_migraciones(ratchet):
    """Ambos nombran ``user_key`` legítimamente. Ver el docstring del script."""
    actuales = ratchet._ficheros_con_user_key()

    assert not [ruta for ruta in actuales if ruta.startswith("tests/")]
    assert not [ruta for ruta in actuales if ruta.startswith("db/alembic/versions/")]


def test_count_imprime_solo_el_numero(ratchet, capsys):
    """`make status` consume esta salida; que no lleve texto alrededor."""
    assert ratchet.main(["--count"]) == 0

    assert capsys.readouterr().out.strip().isdigit()


def test_user_key_from_email_esta_marcada_como_deprecada():
    """El aviso vive en el docstring: es lo que lee quien va a llamarla."""
    from shared.identity import user_key_from_email

    assert user_key_from_email.__doc__ is not None
    assert "deprecated" in user_key_from_email.__doc__
