"""Hooks que exigen los skills obligatorios de CLAUDE.md antes de editar código."""

import io
import json
import runpy
import subprocess
from pathlib import Path
from typing import Any

import pytest

HOOKS = Path(__file__).resolve().parents[1] / ".claude/hooks"


def _hook(nombre: str) -> dict[str, Any]:
    return runpy.run_path(str(HOOKS / nombre), run_name="hook")


def _skill(nombre: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": nombre}}]},
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "repo/.git").mkdir(parents=True)
    return tmp_path / "repo"


def _editar(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    rel: str,
    lineas: list[dict[str, Any] | str],
) -> tuple[int, str]:
    """Lanza el hook de edición sobre `repo/rel`; devuelve (exit code, stderr)."""
    transcript = repo.parent / "sesion.jsonl"
    transcript.write_text(
        "\n".join(x if isinstance(x, str) else json.dumps(x) for x in lineas), encoding="utf-8"
    )
    payload = {
        "tool_input": {"file_path": str(repo / rel)},
        "cwd": str(repo),
        "transcript_path": str(transcript),
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    stderr = io.StringIO()
    monkeypatch.setattr("sys.stderr", stderr)
    try:
        _hook("pretooluse_edit_skills.py")["main"]()
    except SystemExit as salida:
        return int(salida.code or 0), stderr.getvalue()
    return 0, stderr.getvalue()


@pytest.mark.parametrize(
    ("rel", "esperados"),
    [
        ("services/x.py", ["ponytail"]),
        ("web/src/app/page.tsx", ["ponytail", "impeccable"]),
        ("web/src/app/globals.css", ["impeccable"]),
        ("db/repositories/x.py", ["ponytail", "supabase-postgres-best-practices"]),
        (
            "db/alembic/versions/v1.py",
            ["ponytail", "sqlalchemy-alembic-expert-best-practices-code-review"],
        ),
        ("api/routes/x.py", ["ponytail", "fastapi-python"]),
        ("tests/test_unit_x.py", ["ponytail", "python-testing-patterns"]),
        ("docs/README.md", []),
        ("pyproject.toml", []),
        ("web/node_modules/lib/index.ts", []),
        (".claude/skills/impeccable/scripts/x.py", []),
    ],
)
def test_tabla_area_skill(rel: str, esperados: list[str]) -> None:
    exigidos = _hook("pretooluse_edit_skills.py")["skills_exigidos"](rel)

    assert [skill for skill, _ in exigidos] == esperados


def test_bloquea_sql_sin_el_skill_de_postgres(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codigo, stderr = _editar(repo, monkeypatch, "db/repositories/x.py", [_skill("ponytail")])

    assert codigo == 2
    assert "`supabase-postgres-best-practices`" in stderr
    assert "`ponytail`" not in stderr


def test_deja_pasar_con_los_skills_cargados(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lineas: list[dict[str, Any] | str] = [
        _skill("ponytail"),
        _skill("supabase:supabase-postgres-best-practices"),  # prefijo de plugin
    ]

    assert _editar(repo, monkeypatch, "db/repositories/x.py", lineas) == (0, "")


def test_el_slash_command_del_usuario_cuenta_como_cargado(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    usuario = {"type": "user", "message": {"content": "<command-name>/impeccable</command-name>"}}

    assert _editar(repo, monkeypatch, "web/src/app/globals.css", [usuario])[0] == 0


def _editar_desde_subagente(
    repo: Path, monkeypatch: pytest.MonkeyPatch, skills_del_agente: list[str]
) -> int:
    """El hook recibe el transcript principal (vacío) y el `agent_id` del subagente."""
    principal = repo.parent / "sesion.jsonl"
    principal.write_text("", encoding="utf-8")
    del_agente = repo.parent / "sesion" / "subagents" / "agent-abc123.jsonl"
    del_agente.parent.mkdir(parents=True, exist_ok=True)
    del_agente.write_text(
        "\n".join(json.dumps(_skill(s)) for s in skills_del_agente), encoding="utf-8"
    )
    payload = {
        "tool_input": {"file_path": str(repo / "tests/test_unit_x.py")},
        "cwd": str(repo),
        "transcript_path": str(principal),
        "agent_id": "abc123",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr("sys.stderr", io.StringIO())
    try:
        _hook("pretooluse_edit_skills.py")["main"]()
    except SystemExit as salida:
        return int(salida.code or 0)
    return 0


def test_dentro_de_un_subagente_cuentan_sus_skills(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Antes solo se leía el transcript principal y se bloqueaba al subagente que sí los cargó."""
    assert _editar_desde_subagente(repo, monkeypatch, ["ponytail", "python-testing-patterns"]) == 0


def test_dentro_de_un_subagente_sin_skills_sigue_bloqueando(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _editar_desde_subagente(repo, monkeypatch, ["ponytail"]) == 2


def test_un_agent_id_raro_no_sale_del_directorio(tmp_path: Path) -> None:
    transcripts = _hook("pretooluse_edit_skills.py")["transcripts"]
    principal = tmp_path / "sesion.jsonl"
    principal.write_text("", encoding="utf-8")

    assert transcripts({"transcript_path": str(principal), "agent_id": "../../x"}) == [principal]


def test_docs_y_configuracion_no_exigen_nada(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _editar(repo, monkeypatch, "docs/README.md", [])[0] == 0


def test_lineas_ilegibles_no_rompen_la_lectura(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lineas: list[dict[str, Any] | str] = ['{"Skill": roto', _skill("ponytail")]

    assert _editar(repo, monkeypatch, "services/x.py", lineas)[0] == 0


def test_sin_transcript_deja_pasar(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "tool_input": {"file_path": str(repo / "services/x.py")},
        "cwd": str(repo),
        "transcript_path": str(repo / "no-existe.jsonl"),
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

    _hook("pretooluse_edit_skills.py")["main"]()  # no lanza SystemExit


def test_fuera_del_repo_no_exige_nada(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    transcript = tmp_path / "sesion.jsonl"
    transcript.write_text("", encoding="utf-8")
    payload = {
        "tool_input": {"file_path": str(tmp_path / "scratch/x.py")},
        "cwd": str(tmp_path),
        "transcript_path": str(transcript),
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    hook = _hook("pretooluse_edit_skills.py")
    # Sin `.git` por encima de tmp_path la raíz cae en el repo del hook.
    hook["main"]()


def _entregar(
    monkeypatch: pytest.MonkeyPatch, comando: str, diff: str
) -> tuple[str, list[list[str]]]:
    llamadas: list[list[str]] = []

    def git(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        llamadas.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=diff, stderr="")

    monkeypatch.setattr(subprocess, "run", git)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_input": {"command": comando}})))
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)
    _hook("pretooluse_bash_revision_visual.py")["main"]()
    return stdout.getvalue(), llamadas


@pytest.mark.parametrize("comando", ['git commit -m "x"', "gh pr create --fill"])
def test_avisa_de_la_revision_visual_si_hay_web_src(
    monkeypatch: pytest.MonkeyPatch, comando: str
) -> None:
    salida, _ = _entregar(monkeypatch, comando, "web/src/a.tsx\napi/x.py\n")

    contexto = json.loads(salida)["hookSpecificOutput"]["additionalContext"]
    assert "web/src/a.tsx" in contexto
    assert "api/x.py" not in contexto
    assert "Vercel" in contexto


def test_sin_web_src_no_avisa(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _entregar(monkeypatch, 'git commit -m "x"', "api/x.py\n")[0] == ""


def test_otros_comandos_no_miran_el_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    salida, llamadas = _entregar(monkeypatch, "git status", "web/src/a.tsx\n")

    assert (salida, llamadas) == ("", [])
