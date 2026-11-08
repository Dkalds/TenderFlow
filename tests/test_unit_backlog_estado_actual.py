"""Cada ítem abierto del backlog empieza por su «Estado actual» (AGENTS.md §0).

El 2026-11-07 un informe de mejoras leyó solo el «Problema» de cada ítem, que se
queda en el día en que se abrió, y propuso como pendientes cinco cosas hechas.
`scripts/check_backlog_freshness.py` falla desde entonces si un ítem no abre
con la línea que dice qué queda hoy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import check_backlog_freshness as chequeo

_CABECERA = "# Improvement Backlog\n\n## P1 — Alta\n\n"
_PLANTILLA = "\n## Plantilla nueva entrada\n\n### [P0|P1|P2|P3] Título\n- **Área:** x\n"


def _correr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: str) -> int:
    backlog = tmp_path / "IMPROVEMENT_BACKLOG.md"
    backlog.write_text(_CABECERA + items + _PLANTILLA, encoding="utf-8")
    monkeypatch.setattr(chequeo, "_BACKLOG", backlog)
    monkeypatch.setattr(chequeo.sys, "argv", ["check_backlog_freshness.py"])
    return chequeo.main()


@pytest.mark.parametrize("clase", ["código", "propietario", "medir", "mixto"])
def test_un_item_con_estado_actual_pasa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clase: str
) -> None:
    item = f"### [P1] Algo\n- **Estado actual (2026-11-08):** `{clase}` — queda X.\n"
    assert _correr(tmp_path, monkeypatch, item) == 0


def test_un_item_que_empieza_por_el_problema_falla(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    item = "### [P1] Algo\n- **Problema:** está roto.\n"

    assert _correr(tmp_path, monkeypatch, item) == 1
    assert "'Algo' no empieza por" in capsys.readouterr().out


@pytest.mark.parametrize(
    "linea",
    [
        "- **Estado actual:** `código` — sin fecha.",
        "- **Estado actual (2026-11-08):** `pendiente` — clase fuera del vocabulario.",
        "- **Área:** x\n- **Estado actual (2026-11-08):** `código` — no es la primera.",
    ],
)
def test_un_estado_actual_mal_formado_falla(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, linea: str
) -> None:
    assert _correr(tmp_path, monkeypatch, f"### [P2] Algo\n{linea}\n") == 1


def test_la_plantilla_no_cuenta_como_item(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _correr(tmp_path, monkeypatch, "") == 0
