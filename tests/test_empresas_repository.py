"""``db/repositories/empresas.py::get_empresa``: la ficha de una empresa con su UTE.

Contra Postgres (``tmp_db``): una UTE con dos miembros, uno de ellos con alias.
La ficha del miembro dice en qué UTE participa; la de la UTE, quiénes la forman.
"""

from __future__ import annotations

_AHORA = "2026-11-04T00:00:00+00:00"


def _empresa(c, empresa_id: int, nombre: str, *, es_ute: int = 0) -> None:
    c.execute(
        "INSERT INTO empresas (empresa_id, nif_canonico, nombre_canonico, es_ute, "
        "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (empresa_id, f"B{empresa_id:08d}", nombre, es_ute, _AHORA, _AHORA),
    )


def _sembrar(db_mod) -> None:
    with db_mod.connect() as c:
        _empresa(c, 1, "ALFA SL")
        _empresa(c, 2, "BETA SA")
        _empresa(c, 3, "UTE ALFA BETA", es_ute=1)
        c.execute(
            "INSERT INTO ute_miembros (ute_empresa_id, miembro_empresa_id) VALUES (3, 1), (3, 2)"
        )
        c.execute(
            "INSERT INTO empresa_aliases (empresa_id, alias_normalizado, fuente, confianza, "
            "created_at) VALUES (1, 'alfa', 'test', 1.0, %s)",
            (_AHORA,),
        )


def test_la_ficha_de_un_miembro_trae_alias_y_la_ute_en_la_que_participa(tmp_db):
    from db.repositories.empresas import EmpresasReadRepository

    db_mod, _ = tmp_db
    _sembrar(db_mod)

    ficha = EmpresasReadRepository().get_empresa(1)

    assert ficha is not None
    assert ficha["nombre_canonico"] == "ALFA SL"
    assert [a["alias_normalizado"] for a in ficha["aliases"]] == ["alfa"]
    assert ficha["ute_miembros"] == []
    assert ficha["participa_en_utes"] == [{"empresa_id": 3, "nombre_canonico": "UTE ALFA BETA"}]


def test_la_ficha_de_una_ute_trae_a_sus_miembros(tmp_db):
    from db.repositories.empresas import EmpresasReadRepository

    db_mod, _ = tmp_db
    _sembrar(db_mod)

    ficha = EmpresasReadRepository().get_empresa(3)

    assert ficha is not None
    assert sorted(m["empresa_id"] for m in ficha["ute_miembros"]) == [1, 2]
    assert ficha["participa_en_utes"] == []


def test_una_empresa_que_no_existe_es_none(tmp_db):
    from db.repositories.empresas import EmpresasReadRepository

    assert EmpresasReadRepository().get_empresa(999) is None
