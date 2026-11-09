"""Clasificación de ramas de `scripts/cerrar_ramas.py`: qué se puede borrar y qué no."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.cerrar_ramas import (
    ABIERTO,
    CERRADO,
    INTEGRADA,
    POSTERIOR,
    PR,
    SIN_COMMITS,
    SIN_PR,
    SUCIA,
    Rama,
    aprobadas,
    clasificar,
    clave,
    leer_worktrees,
)

# Historia de juguete: "base" está en master; "squash" es la cabeza de un PR
# mergeado con squash; "despues" es un commit local posterior a esa cabeza.
ANCESTROS = {("base", "origin/master"), ("squash", "squash"), ("base", "squash")}


def contenida_en(a: str, b: str) -> bool:
    return (a, b) in ANCESTROS


def limpia(_: Rama) -> bool:
    return False


@pytest.mark.parametrize(
    ("punta", "prs", "esperado"),
    [
        pytest.param("base", [], INTEGRADA, id="ancestro-de-master"),
        pytest.param(
            "squash", [PR(1, "MERGED", "squash", "master")], INTEGRADA, id="squash-mergeada"
        ),
        pytest.param(
            "despues", [PR(1, "MERGED", "squash", "master")], POSTERIOR, id="commits-tras-el-merge"
        ),
        pytest.param(
            "despues",
            [PR(1, "MERGED", "squash", "master"), PR(2, "OPEN", "despues", "master")],
            ABIERTO,
            id="reabierta",
        ),
        pytest.param(
            "despues", [PR(1, "CLOSED", "despues", "master")], CERRADO, id="cerrada-sin-merge"
        ),
        pytest.param("despues", [], SIN_PR, id="sin-pr"),
        pytest.param(
            "squash",
            [PR(1, "MERGED", "squash", "agente/a")],
            POSTERIOR,
            id="pr-apilado-no-llego-a-master",
        ),
    ],
)
def test_clasificar_por_ancestro_y_pr(punta: str, prs: list[PR], esperado: str) -> None:
    assert clasificar(Rama("agente/x", punta, None), prs, contenida_en, limpia) == esperado


def test_clasificar_conserva_worktree_integrado_con_cambios() -> None:
    rama = Rama("agente/x", "base", Path("/wt/x"))

    assert clasificar(rama, [], contenida_en, lambda _: True) == SUCIA


def test_leer_worktrees_omite_el_principal_y_los_podables() -> None:
    porcelain = (
        "worktree /repo\nHEAD aaa\nbranch refs/heads/master\n\n"
        "worktree /repo/.claude/worktrees/a\nHEAD bbb\nbranch refs/heads/agente/a\n\n"
        "worktree /repo/.claude/worktrees/b\nHEAD ccc\ndetached\n\n"
        "worktree /repo/.claude/worktrees/c\nHEAD ddd\nbranch refs/heads/agente/c\nprunable gitdir file points to non-existent location\n"
    )

    assert leer_worktrees(porcelain) == [
        Rama("agente/a", "bbb", Path("/repo/.claude/worktrees/a")),
        Rama(None, "ccc", Path("/repo/.claude/worktrees/b")),
    ]


def test_clasificar_no_borra_worktree_sin_commits_propios() -> None:
    rama = Rama("agente/nueva", "base", Path("/wt/nueva"))

    assert clasificar(rama, [], contenida_en, limpia) == SIN_COMMITS


def test_aprobadas_solo_lo_ya_listado() -> None:
    vista = Rama("agente/a", "x", Path("/wt/a"))
    nueva = Rama("agente/b", "y", None)

    assert aprobadas([vista, nueva], {clave(vista)}) == [vista]
