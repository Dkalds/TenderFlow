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
import sys
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
    arranca: bool = True,
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
    _cli_arranca(monkeypatch, arranca)
    try:
        runpy.run_path(str(HOOKS / "pretooluse_bash_grep_hint.py"), run_name="hook")
    except SystemExit as salida:
        return int(salida.code or 0), stderr.getvalue()
    return 0, stderr.getvalue()


def _cli_arranca(monkeypatch: pytest.MonkeyPatch, arranca: bool = True) -> None:
    """`graphify --help` responde, o falla como lo bloquea el Control de aplicaciones de Windows."""

    def run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        if not arranca:
            raise PermissionError(
                4551, "Una directiva de Control de aplicaciones bloqueó este archivo"
            )
        return subprocess.CompletedProcess(args=[], returncode=0)

    monkeypatch.setattr(subprocess, "run", run)


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


def test_un_cli_que_no_arranca_no_bloquea_y_remite_a_code_map(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """En el PATH pero bloqueado: exigir `graphify query` sería pedir lo imposible."""
    (repo / "scripts").mkdir()
    (repo / "scripts/code_map.py").touch()
    assert _buscar(repo, monkeypatch, _SIN_GRAFO, arranca=False)[0] == 0
    assert "code_map.py" in sys.stdout.getvalue()


# ── Arranque de sesión: no prometer lo que la máquina no puede hacer ───────


def _contexto() -> dict[str, Any]:
    return runpy.run_path(str(HOOKS / "session_start_contexto.py"), run_name="hook")


def test_el_arranque_avisa_si_graphify_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _contexto()
    monkeypatch.setattr("shutil.which", lambda nombre: "/bin/graphify")
    _cli_arranca(monkeypatch, arranca=False)
    assert "code_map.py" in hook["aviso_graphify"]()


def test_el_arranque_calla_si_graphify_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _contexto()
    monkeypatch.setattr("shutil.which", lambda nombre: "/bin/graphify")
    _cli_arranca(monkeypatch)
    assert hook["aviso_graphify"]() == ""


@pytest.mark.parametrize(("salida", "hay"), [("", False), ("U\x00b\x00u\x00n\x00t\x00u\x00", True)])
def test_wsl_solo_cuenta_con_alguna_distro(
    monkeypatch: pytest.MonkeyPatch, salida: str, hay: bool
) -> None:
    """Windows trae `wsl.exe` siempre; sin distro, `wsl -l -q` sale vacío."""
    hook = _contexto()
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=salida)
    )
    assert hook["hay_distro_wsl"]() is hay


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


# ── Bordes: lo que no se sabe leer nunca bloquea ────────────────────────────


def _correr_busqueda(monkeypatch: pytest.MonkeyPatch, stdin: str) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    monkeypatch.setattr("sys.stdout", io.StringIO())
    try:
        runpy.run_path(str(HOOKS / "pretooluse_bash_grep_hint.py"), run_name="hook")
    except SystemExit as salida:
        return int(salida.code or 0)
    return 0


def test_lineas_ilegibles_y_bloques_sin_llamada_se_saltan(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = repo.parent / "sesion.jsonl"
    transcript.write_text(
        "\n".join(
            [
                "{no es json tool_use",
                json.dumps({"message": {"content": [{"type": "text", "text": "tool_use"}]}}),
                json.dumps(_uso("Bash", command="git status")),
            ]
        ),
        encoding="utf-8",
    )
    hook = runpy.run_path(str(HOOKS / "pretooluse_bash_grep_hint.py"), run_name="sin_stdin")
    assert hook["grafo_consultado"](transcript) is False


def test_una_entrada_que_no_es_json_no_bloquea(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _correr_busqueda(monkeypatch, "no es json") == 0


def test_sin_transcript_avisa_sin_bloquear(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"tool_name": "Grep", "tool_input": {"pattern": "x"}, "cwd": str(repo)}
    monkeypatch.setattr("shutil.which", lambda nombre: "/bin/graphify")
    assert _correr_busqueda(monkeypatch, json.dumps(payload)) == 0


def test_un_fallo_interno_no_bloquea(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    transcript = repo.parent / "sesion.jsonl"
    transcript.write_text(json.dumps(_uso("Bash", command="ls")), encoding="utf-8")
    payload = {
        "tool_name": "Grep",
        "tool_input": {"pattern": "x"},
        "cwd": str(repo),
        "transcript_path": str(transcript),
    }

    def revienta(nombre: str) -> str:
        raise OSError("PATH ilegible")

    monkeypatch.setattr("shutil.which", revienta)
    assert _correr_busqueda(monkeypatch, json.dumps(payload)) == 0


def test_el_bloqueo_escribe_en_utf8_aunque_stderr_sea_cp1252(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    crudo = io.BytesIO()
    monkeypatch.setattr("sys.stderr", io.TextIOWrapper(crudo, encoding="cp1252"))
    transcript = repo.parent / "sesion.jsonl"
    transcript.write_text(json.dumps(_uso("Bash", command="ls")), encoding="utf-8")
    payload = {
        "tool_name": "Grep",
        "tool_input": {"pattern": "x"},
        "cwd": str(repo),
        "transcript_path": str(transcript),
    }
    monkeypatch.setattr("shutil.which", lambda nombre: "/bin/graphify")
    _cli_arranca(monkeypatch)
    assert _correr_busqueda(monkeypatch, json.dumps(payload)) == 2
    sys.stderr.flush()
    assert "Búsqueda bloqueada" in crudo.getvalue().decode("utf-8")


@pytest.mark.parametrize("sistema", ["nt", "posix"])
def test_el_refresco_se_lanza_desligado_del_turno(
    repo: Path, monkeypatch: pytest.MonkeyPatch, sistema: str
) -> None:
    hook = _refresco()
    (repo / "graphify-out/.graph_stale").touch()
    monkeypatch.setattr("shutil.which", lambda nombre: "/bin/graphify")
    monkeypatch.setattr(os, "name", sistema)
    opciones: dict[str, Any] = {}
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: opciones.update(k))

    assert hook["lanzar"](repo) is True
    assert ("creationflags" in opciones) is (sistema == "nt")
    assert opciones.get("start_new_session", False) is (sistema != "nt")


def test_sin_cli_el_refresco_no_hace_nada(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _refresco()
    (repo / "graphify-out/.graph_stale").touch()
    monkeypatch.setattr("shutil.which", lambda nombre: None)
    assert hook["refrescar"](repo) == 1
    assert (repo / "graphify-out/.graph_stale").exists()


def test_main_lanza_desde_el_cwd_y_refresca_con_su_argumento(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = _refresco()
    (repo / "graphify-out/.graph_stale").touch()
    monkeypatch.setattr("shutil.which", lambda nombre: "/bin/graphify")
    lanzados: list[object] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: lanzados.append(a))
    monkeypatch.setattr("sys.argv", ["stop_graph_refresh.py"])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(repo / "graphify-out")})))
    hook["main"]()
    assert len(lanzados) == 1

    monkeypatch.setattr("sys.stdin", io.StringIO("no es json"))
    hook["main"]()  # una entrada ilegible no rompe ni lanza otro
    assert len(lanzados) == 1

    _con_update(monkeypatch, 0)
    monkeypatch.setattr("sys.argv", ["stop_graph_refresh.py", "--refrescar", str(repo)])
    hook["main"]()
    assert not (repo / "graphify-out/.graph_stale").exists()


def test_sin_pistas_la_raiz_es_la_del_propio_hook() -> None:
    hook = _refresco()
    assert hook["raiz_del_checkout"]("", "relativa") == hook["ROOT"]
