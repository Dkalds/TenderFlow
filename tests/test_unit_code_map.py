"""``scripts/code_map.py``: el mapa del código que usa una sesión sin el CLI de graphify.

Es el paso 2 de AGENTS.md §1. Si deja de encontrar una definición o un
importador, un agente remoto vuelve a buscar texto a ciegas sin saber que la
herramienta le está fallando: estos tests fijan lo que promete su docstring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import code_map


def _escribir(root: Path, fichero: str, contenido: str) -> None:
    destino = root / fichero
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(contenido, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _escribir(tmp_path, "db/__init__.py", "")
    _escribir(
        tmp_path,
        "db/upsert.py",
        '"""Upsert idempotente."""\n\n\n'
        "def upsert_licitaciones(filas):\n    return len(filas)\n\n\n"
        "class Lote:\n    def guardar(self):\n        return 1\n\n\n"
        "def _privada():\n    return 0\n",
    )
    _escribir(tmp_path, "services/__init__.py", "")
    _escribir(
        tmp_path,
        "services/ingesta.py",
        "from db.upsert import upsert_licitaciones\n\n\n"
        "def ingerir(filas):\n    return upsert_licitaciones(filas)\n",
    )
    _escribir(
        tmp_path,
        "services/diferido.py",
        "def tarde():\n    import db.upsert\n\n    return db.upsert.Lote().guardar()\n",
    )
    _escribir(
        tmp_path, "services/relativo.py", "from . import ingesta\nfrom .ingesta import ingerir\n"
    )
    _escribir(
        tmp_path,
        "services/ajeno.py",
        "import json\n\n\ndef upsert_licitaciones():\n    return json\n",
    )
    _escribir(
        tmp_path,
        "tests/test_upsert.py",
        "from db import upsert\n\n\ndef test_upsert():\n    assert upsert.upsert_licitaciones([]) == 0\n",
    )
    _escribir(tmp_path, "services/roto.py", "def (:\n")
    _escribir(tmp_path, ".venv/lib/vendor.py", "from db.upsert import upsert_licitaciones\n")
    return tmp_path


def test_el_indice_ignora_lo_que_no_es_codigo_del_proyecto_y_lo_que_no_parsea(repo: Path) -> None:
    indice = code_map.indexar(repo)

    assert "db.upsert" in indice
    assert "db" in indice  # el __init__ es el paquete
    assert "services.roto" not in indice
    assert not any(nombre.startswith(".venv") for nombre in indice)


def test_importadores_cuenta_imports_diferidos_relativos_y_from_paquete_import_modulo(
    repo: Path,
) -> None:
    indice = code_map.indexar(repo)

    de_upsert = {m.fichero for m in code_map.importadores(indice, "db.upsert")}
    de_ingesta = {m.fichero for m in code_map.importadores(indice, "services.ingesta")}

    assert de_upsert == {"services/ingesta.py", "services/diferido.py", "tests/test_upsert.py"}
    assert de_ingesta == {"services/relativo.py"}


def test_simbolo_da_la_definicion_y_solo_los_usos_de_quien_importa_su_modulo(repo: Path) -> None:
    indice = code_map.indexar(repo)

    salida = "\n".join(code_map.cmd_simbolo(indice, "upsert_licitaciones", 40))

    assert "función upsert_licitaciones  db/upsert.py:4" in salida
    assert "services/ingesta.py:5" in salida
    assert "tests/test_upsert.py:5" in salida
    # Hay otra función con el mismo nombre en un módulo que nadie importa: se
    # lista como definición aparte y no hereda los usos de la primera.
    assert "función upsert_licitaciones  services/ajeno.py:4" in salida
    assert salida.count("services/ingesta.py") == 1


def test_simbolo_encuentra_un_metodo_por_su_nombre(repo: Path) -> None:
    indice = code_map.indexar(repo)

    salida = "\n".join(code_map.cmd_simbolo(indice, "guardar", 40))

    assert "método Lote.guardar  db/upsert.py:9" in salida
    assert "services/diferido.py:4" in salida


def test_paquete_lista_la_api_publica_y_acepta_ruta_o_nombre(repo: Path) -> None:
    indice = code_map.indexar(repo)

    por_ruta = code_map.cmd_paquete(indice, "db/", 40)
    por_nombre = code_map.cmd_paquete(indice, "db", 40)

    assert por_ruta == por_nombre
    texto = "\n".join(por_ruta)
    assert "Upsert idempotente." in texto
    assert "upsert_licitaciones, Lote" in texto
    assert "_privada" not in texto


def test_fichero_separa_los_imports_del_repo_de_los_de_terceros(repo: Path) -> None:
    indice = code_map.indexar(repo)

    salida = "\n".join(code_map.cmd_fichero(indice, "services/ajeno.py", 40))

    assert "importa del repo (0)" in salida
    assert "función upsert_licitaciones" in salida


@pytest.mark.parametrize(
    ("comando", "objetivo", "esperado"),
    [
        ("simbolo", "no_existe", "Sin definición"),
        ("importadores", "no.existe", "no es un módulo"),
        ("paquete", "nada", "no es un paquete"),
        ("fichero", "nada.py", "no es un fichero"),
    ],
)
def test_un_objetivo_desconocido_lo_dice_en_vez_de_devolver_vacio(
    repo: Path, capsys: pytest.CaptureFixture[str], comando: str, objetivo: str, esperado: str
) -> None:
    assert code_map.main([comando, objetivo], root=repo) == 0
    assert esperado in capsys.readouterr().out


def test_las_listas_largas_se_recortan_diciendo_cuanto_falta() -> None:
    assert code_map._recortar(["a", "b", "c"], 2) == ["a", "b", "… y 1 más (--max para verlos)"]
