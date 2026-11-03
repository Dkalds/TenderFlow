"""Hooks del grafo de graphify: la primera búsqueda espera al grafo, y el grafo se refresca solo.

En la sesión del PR #650 el grafo estaba disponible y no se consultó ni se
refrescó: el aviso de una vez por sesión se ignoró. Lo que se fija aquí es que
ahora bloquea cuando debe (y solo entonces) y que el refresco no borra la marca
de un grafo que se volvió a ensuciar mientras se rehacía.
"""

from __future__ import annotations

import io
import json
import os
import runpy
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

HOOKS = Path(__file__).resolve().parents[1] / ".claude/hooks"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    raiz = tmp_path / "repo"
    (raiz / ".git").mkdir(parents=True)
    (raiz / "graphify-out").mkdir()
    (raiz / "graphify-out/graph.json").write_text("{}", encoding="utf-8")
    return raiz


def _uso(nombre: str, **entrada: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": nombre, "input": entrada}]},
    }


def _buscar(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    lineas: list[dict[str, Any]],
    *,
    herramienta: str = "Bash",
    comando: str = "rg TODO",
    cli: bool = True,
) -> tuple[int, str]:
    """Lanza el hook de búsqueda; devuelve (exit code, stderr)."""
    transcript = repo.parent / "sesion.jsonl"
    transcript.write_text("\n".join(json.dumps(x) for x in lineas), encoding="utf-8")
    entrada = {"pattern": "TODO"} if herramienta == "Grep" else {"command": comando}
    payload = {
        "tool_name": herramienta,
        "tool_input": entrada,
        "cwd": str(repo),
        "transcript_path": str(transcript),
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr("sys.stdout", io.StringIO())
    stderr = io.StringIO()
    monkeypatch.setattr("sys.stderr", stderr)
    monkeypatch.setattr("shutil.which", lambda nombre: "/bin/graphify" if cli else None)
    try:
        runpy.run_path(str(HOOKS / "pretooluse_bash_grep_hint.py"), run_name="hook")
    except SystemExit as salida:
        return int(salida.code or 0), stderr.getvalue()
    return 0, stderr.getvalue()


_SIN_GRAFO = [_uso("Bash", command="git status"), _uso("Read", file_path="x.py")]


def test_la_primera_busqueda_espera_al_grafo(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codigo, mensaje = _buscar(repo, monkeypatch, _SIN_GRAFO)
    assert codigo == 2
    assert "graphify query" in mensaje


def test_tambien_la_herramienta_grep(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _buscar(repo, monkeypatch, _SIN_GRAFO, herramienta="Grep")[0] == 2


@pytest.mark.parametrize(
    "consulta",
    [
        _uso("Bash", command='graphify query "quién llama a perfil_empresa"'),
        _uso("Bash", command="cd repo && graphify explain _llamar_modelo"),
        _uso("mcp__graphify__query_graph", question="x"),
    ],
)
def test_tras_consultar_el_grafo_la_busqueda_queda_libre(
    repo: Path, monkeypatch: pytest.MonkeyPatch, consulta: dict[str, Any]
) -> None:
    assert _buscar(repo, monkeypatch, [*_SIN_GRAFO, consulta])[0] == 0


def test_citar_graphify_en_un_texto_no_cuenta(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDE.md y el propio mensaje del hook dicen «graphify query»: no es consultarlo."""
    texto = {"type": "user", "message": {"content": 'usa `graphify query "x"` antes de grep'}}
    assert _buscar(repo, monkeypatch, [*_SIN_GRAFO, texto])[0] == 2


def test_un_filtro_de_tuberia_no_es_una_busqueda(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _buscar(repo, monkeypatch, _SIN_GRAFO, comando="git ls-files | grep py")[0] == 0


def test_sin_cli_no_bloquea(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _buscar(repo, monkeypatch, _SIN_GRAFO, cli=False)[0] == 0


def test_un_transcript_de_otro_cliente_no_bloquea(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin bloques ``tool_use`` (Codex) no se sabe si consultó el grafo: no se bloquea."""
    codex = [{"type": "response_item", "payload": {"type": "function_call", "name": "shell"}}]
    assert _buscar(repo, monkeypatch, codex)[0] == 0


# ── Refresco al acabar el turno ─────────────────────────────────────────────


def _refresco() -> dict[str, Any]:
    return runpy.run_path(str(HOOKS / "stop_graph_refresh.py"), run_name="hook")


def test_sin_marca_no_lanza_nada(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _refresco()
    monkeypatch.setattr("shutil.which", lambda nombre: "/bin/graphify")
    lanzados: list[object] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: lanzados.append(a))
    assert hook["lanzar"](repo) is False
    assert lanzados == []


def test_con_marca_lanza_una_vez_y_respeta_el_cerrojo(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = _refresco()
    (repo / "graphify-out/.graph_stale").touch()
    monkeypatch.setattr("shutil.which", lambda nombre: "/bin/graphify")
    lanzados: list[object] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: lanzados.append(a))

    assert hook["lanzar"](repo) is True
    assert hook["lanzar"](repo) is False  # el primero sigue en marcha
    assert len(lanzados) == 1


def _con_update(monkeypatch: pytest.MonkeyPatch, codigo: int, efecto: Any = None) -> None:
    def run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        if efecto:
            efecto()
        return subprocess.CompletedProcess(args=[], returncode=codigo)

    monkeypatch.setattr("shutil.which", lambda nombre: "/bin/graphify")
    monkeypatch.setattr(subprocess, "run", run)


def test_un_refresco_bueno_borra_la_marca_y_el_cerrojo(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = _refresco()
    (repo / "graphify-out/.graph_stale").touch()
    (repo / "graphify-out/.refrescando").touch()
    _con_update(monkeypatch, 0)

    assert hook["refrescar"](repo) == 0
    assert not (repo / "graphify-out/.graph_stale").exists()
    assert not (repo / "graphify-out/.refrescando").exists()


def test_una_edicion_durante_el_refresco_conserva_la_marca(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = _refresco()
    marca = repo / "graphify-out/.graph_stale"
    marca.touch()
    antes = marca.stat().st_mtime

    def editar() -> None:
        os.utime(marca, (time.time(), antes + 5))

    _con_update(monkeypatch, 0, editar)
    hook["refrescar"](repo)
    assert marca.exists()


def test_un_refresco_fallido_conserva_la_marca(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _refresco()
    (repo / "graphify-out/.graph_stale").touch()
    _con_update(monkeypatch, 1)

    assert hook["refrescar"](repo) == 1
    assert (repo / "graphify-out/.graph_stale").exists()
    assert not (repo / "graphify-out/.refrescando").exists()
