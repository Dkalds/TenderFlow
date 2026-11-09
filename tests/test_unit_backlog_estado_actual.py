"""Cada ítem abierto del backlog empieza por su «Estado actual» (AGENTS.md §0).

El 2026-11-07 un informe de mejoras leyó solo el «Problema» de cada ítem, que se
queda en el día en que se abrió, y propuso como pendientes cinco cosas hechas.
`scripts/check_backlog_freshness.py` falla desde entonces si un ítem no abre
con la línea que dice qué queda hoy.
"""

from __future__ import annotations

import io
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


_ESTADO = "- **Estado actual (2026-11-08):** `medir` — queda mirar el log.\n"


@pytest.mark.parametrize(
    "nota",
    [
        "- **Progreso (2026-11-09):** hecho el arreglo.",
        "- *Estado (2026-11-10):* ya está en producción.",
        "  **Medido 2026-11-12 (log de Render):** sale bien.",
    ],
)
def test_una_nota_posterior_al_estado_actual_falla(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], nota: str
) -> None:
    item = f"### [P2] Algo\n{_ESTADO}- **Problema:** x.\n{nota}\n"

    assert _correr(tmp_path, monkeypatch, item) == 1
    assert "Reescribe el Estado actual" in capsys.readouterr().out


@pytest.mark.parametrize(
    "nota",
    [
        "- **Progreso (2026-11-08):** del mismo día que el estado.",
        "- **Progreso (2026-10-01):** anterior.",
        "- **Hecho:** la v2 se desactivó en producción (2026-12-01), fecha en la prosa.",
    ],
)
def test_notas_que_no_desactualizan_el_estado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nota: str
) -> None:
    item = f"### [P2] Algo\n{_ESTADO}{nota}\n"

    assert _correr(tmp_path, monkeypatch, item) == 0


def test_un_estado_que_cita_un_fichero_inexistente_falla(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    item = (
        "### [P2] Algo\n- **Estado actual (2026-11-08):** `código` — retirar "
        "`scheduler/no_existe_este_job.py`.\n"
    )

    assert _correr(tmp_path, monkeypatch, item) == 1
    assert "scheduler/no_existe_este_job.py" in capsys.readouterr().out


def test_un_estado_que_cita_un_fichero_existente_pasa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = (
        "### [P2] Algo\n- **Estado actual (2026-11-08):** `código` — tocar "
        "`scripts/check_backlog_freshness.py`.\n"
    )

    assert _correr(tmp_path, monkeypatch, item) == 0


def test_el_resumen_da_clase_y_estado_sin_el_resto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    item = f"### [P2] Algo\n{_ESTADO}- **Problema:** texto largo que no debe salir.\n"
    backlog = tmp_path / "IMPROVEMENT_BACKLOG.md"
    backlog.write_text(_CABECERA + item + _PLANTILLA, encoding="utf-8")
    monkeypatch.setattr(chequeo, "_BACKLOG", backlog)
    monkeypatch.setattr(chequeo.sys, "argv", ["check_backlog_freshness.py", "--estado"])

    assert chequeo.main() == 0
    salida = capsys.readouterr().out
    assert "[P2] `medir` Algo\n    queda mirar el log." in salida
    assert "Problema" not in salida


def test_el_resumen_no_falla_con_una_salida_cp1252(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """En Windows, stdout en tubería es cp1252, que no tiene «≥»."""
    item = "### [P2] Algo\n- **Estado actual (2026-11-08):** `medir` — con ≥ 30 pares.\n"
    backlog = tmp_path / "IMPROVEMENT_BACKLOG.md"
    backlog.write_text(_CABECERA + item + _PLANTILLA, encoding="utf-8")
    salida = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(chequeo, "_BACKLOG", backlog)
    monkeypatch.setattr(chequeo.sys, "argv", ["check_backlog_freshness.py", "--estado"])
    monkeypatch.setattr(chequeo.sys, "stdout", salida)

    assert chequeo.main() == 0
    salida.flush()
    assert "con ≥ 30 pares.".encode() in salida.buffer.getvalue()
