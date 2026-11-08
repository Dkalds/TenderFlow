"""Hook UserPromptSubmit que recuerda verificar una mejora antes de proponerla.

Los prompts de los casos son los de la sesión del 2026-11-07 en la que un
informe propuso como pendientes cinco cosas hechas (AGENTS.md §0).
"""

import io
import json
import runpy
from pathlib import Path
from typing import Any

import pytest

HOOK = "userprompt_verificar_mejoras.py"
RAIZ = Path(__file__).resolve().parents[1]


def _lanzar(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], entrada: str
) -> str:
    monkeypatch.setattr("sys.stdin", io.StringIO(entrada))
    hook: dict[str, Any] = runpy.run_path(str(RAIZ / ".claude/hooks" / HOOK), run_name="hook")
    assert hook["main"]() == 0
    return capsys.readouterr().out


@pytest.mark.parametrize(
    "prompt",
    [
        "Que mejoras significativas harias a la app?",
        "Que queda?",
        "¿Qué falta del backlog?",
        "Implementa las mejoras pendientes",
    ],
)
def test_avisa_cuando_se_piden_mejoras(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], prompt: str
) -> None:
    salida = json.loads(_lanzar(monkeypatch, capsys, json.dumps({"prompt": prompt})))

    contexto = salida["hookSpecificOutput"]
    assert contexto["hookEventName"] == "UserPromptSubmit"
    assert "make backlog-estado" in contexto["additionalContext"]
    # Codex lo pone tras el mensaje del usuario: no puede leerse como la tarea.
    assert contexto["additionalContext"].startswith("Nota sobre la petición anterior")


@pytest.mark.parametrize(
    "prompt", ["Porque fallo el ultimo deploy de render?", "Sigue", "Ya las puse, revisa el log"]
)
def test_calla_en_lo_demas(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], prompt: str
) -> None:
    assert _lanzar(monkeypatch, capsys, json.dumps({"prompt": prompt})) == ""


@pytest.mark.parametrize("entrada", ["", "no es json", "[]", '{"prompt": 3}'])
def test_una_entrada_rara_no_rompe_el_turno(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], entrada: str
) -> None:
    assert _lanzar(monkeypatch, capsys, entrada) == ""


def test_la_copia_de_codex_es_la_misma() -> None:
    claude = (RAIZ / ".claude/hooks" / HOOK).read_bytes().replace(b"\r\n", b"\n")
    codex = (RAIZ / ".codex/hooks" / HOOK).read_bytes().replace(b"\r\n", b"\n")
    assert claude == codex
