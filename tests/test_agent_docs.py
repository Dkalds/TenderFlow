"""Tests for deterministic agent-customization validation."""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import tempfile
import time
import unittest
import uuid
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import check_agent_docs


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _install_locked_skill(root: Path) -> None:
    content = "---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n"
    _write(root / ".claude/skills/demo/SKILL.md", content)
    _write(root / ".agents/skills/demo/SKILL.md", content)
    verified_hash = check_agent_docs.combined_hash(
        check_agent_docs.tree_hashes(root / ".agents/skills/demo")
    )
    _write(
        root / "skills-lock.json",
        json.dumps({"skills": {"demo": {"verifiedHash": verified_hash, "trust": "community"}}}),
    )


class AgentDocsCheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.patchers = [
            patch.object(check_agent_docs, "ROOT", self.root),
            patch.object(check_agent_docs, "COMMANDS_DIR", self.root / ".claude/commands"),
            patch.object(check_agent_docs, "CLAUDE_SKILLS", self.root / ".claude/skills"),
            patch.object(check_agent_docs, "AGENTS_SKILLS", self.root / ".agents/skills"),
        ]
        for patcher in self.patchers:
            patcher.start()
        check_agent_docs.errors.clear()
        check_agent_docs.warnings.clear()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        check_agent_docs.errors.clear()
        check_agent_docs.warnings.clear()
        self.temp_dir.cleanup()

    def test_skill_trees_accept_identical_locked_packages(self) -> None:
        _install_locked_skill(self.root)

        check_agent_docs.check_skill_trees()

        self.assertEqual(check_agent_docs.errors, [])

    def test_skill_trees_reject_auxiliary_file_drift(self) -> None:
        _install_locked_skill(self.root)
        _write(self.root / ".claude/skills/demo/reference.md", "canonical\n")
        _write(self.root / ".agents/skills/demo/reference.md", "diverged\n")

        check_agent_docs.check_skill_trees()

        self.assertTrue(any("`demo` diverge" in error for error in check_agent_docs.errors))

    def test_skill_trees_reject_unlocked_claude_skill(self) -> None:
        _install_locked_skill(self.root)
        _write(
            self.root / ".claude/skills/unlocked/SKILL.md",
            "---\nname: unlocked\ndescription: Unlocked\n---\n",
        )

        check_agent_docs.check_skill_trees()

        self.assertTrue(
            any("unlocked no está declarado" in error for error in check_agent_docs.errors)
        )

    def test_skill_trees_reject_missing_verified_hash(self) -> None:
        content = "---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n"
        _write(self.root / ".claude/skills/demo/SKILL.md", content)
        _write(self.root / ".agents/skills/demo/SKILL.md", content)
        _write(self.root / "skills-lock.json", json.dumps({"skills": {"demo": {}}}))

        check_agent_docs.check_skill_trees()

        self.assertTrue(
            any("no tiene `verifiedHash`" in error for error in check_agent_docs.errors)
        )

    def test_skill_trees_reject_missing_trust(self) -> None:
        _install_locked_skill(self.root)
        lock_path = self.root / "skills-lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        del lock["skills"]["demo"]["trust"]
        _write(lock_path, json.dumps(lock))

        check_agent_docs.check_skill_trees()

        self.assertTrue(any("no tiene `trust`" in error for error in check_agent_docs.errors))

    def test_skill_trees_reject_invalid_trust(self) -> None:
        _install_locked_skill(self.root)
        lock_path = self.root / "skills-lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["skills"]["demo"]["trust"] = "totally-trustworthy"
        _write(lock_path, json.dumps(lock))

        check_agent_docs.check_skill_trees()

        self.assertTrue(any("`trust` inválido" in error for error in check_agent_docs.errors))

    def test_skill_trees_reject_stale_verified_hash(self) -> None:
        _install_locked_skill(self.root)
        updated_content = "---\nname: demo\ndescription: Demo skill\n---\n\n# Demo v2\n"
        _write(self.root / ".claude/skills/demo/SKILL.md", updated_content)
        _write(self.root / ".agents/skills/demo/SKILL.md", updated_content)

        check_agent_docs.check_skill_trees()

        self.assertTrue(
            any("cambió de contenido sin actualizar" in error for error in check_agent_docs.errors)
        )

    def test_command_copies_reject_missing_portable_adapter(self) -> None:
        _write(
            self.root / ".claude/commands/area.md",
            "---\ndescription: Area\n---\n\nBody\n",
        )

        check_agent_docs.check_command_copies()

        self.assertEqual(
            check_agent_docs.errors,
            [
                ".claude/commands/area.md: falta la copia portable "
                ".agents/skills/source-command-area/SKILL.md"
            ],
        )

    def test_command_copies_reject_additional_content(self) -> None:
        _write(
            self.root / ".claude/commands/check.md",
            "---\ndescription: Check\n---\n\nCanonical body\n",
        )
        _write(
            self.root / ".agents/skills/source-command-check/SKILL.md",
            "---\nname: source-command-check\ndescription: Check\n---\n\n"
            "# source-command-check\n\n## Command Template\n\nCanonical body\nExtra\n",
        )

        check_agent_docs.check_command_copies()

        self.assertEqual(
            check_agent_docs.errors,
            [
                ".agents/skills/source-command-check/SKILL.md: divergió de "
                ".claude/commands/check.md (el cuerpo debe coincidir exactamente)"
            ],
        )

    def test_hook_parity_rejects_divergent_adapters(self) -> None:
        _write(self.root / ".claude/hooks/demo.py", "print('claude')\n")
        _write(self.root / ".codex/hooks/demo.py", "print('codex')\n")

        check_agent_docs.check_hook_parity()

        self.assertEqual(
            check_agent_docs.errors,
            ["hooks: el hook `demo.py` diverge entre .claude/hooks y .codex/hooks"],
        )

    def test_opencode_plugins_reject_missing_file(self) -> None:
        _write(
            self.root / ".opencode/opencode.json",
            '{"plugin": [".opencode/plugins/missing.js"]}',
        )

        check_agent_docs.check_opencode_plugins()

        self.assertEqual(
            check_agent_docs.errors,
            [
                ".opencode/opencode.json: referencia un plugin inexistente: "
                "'.opencode/plugins/missing.js'"
            ],
        )

    def test_manual_markers_accept_frozen_exception(self) -> None:
        _write(
            self.root / "tests/test_integration_e2e.py",
            "import pytest\n\n@pytest.mark.integration\nclass TestLegacy:\n    pass\n",
        )
        allowlist = frozenset({("tests/test_integration_e2e.py", "integration", "TestLegacy")})

        with patch.object(check_agent_docs, "MANUAL_CATEGORY_MARKER_ALLOWLIST", allowlist):
            check_agent_docs.check_manual_test_markers()

        self.assertEqual(check_agent_docs.errors, [])

    def test_manual_markers_reject_new_category_marker(self) -> None:
        _write(
            self.root / "tests/test_example.py",
            "import pytest\n\n@pytest.mark.unit\ndef test_example():\n    pass\n",
        )

        with patch.object(check_agent_docs, "MANUAL_CATEGORY_MARKER_ALLOWLIST", frozenset()):
            check_agent_docs.check_manual_test_markers()

        self.assertEqual(
            check_agent_docs.errors,
            [
                "tests/test_example.py: test_example introduce `pytest.mark.unit` manual; "
                "renombrá el test para usar auto-marking"
            ],
        )

    def test_manual_markers_reject_pytestmark_in_module_and_class(self) -> None:
        _write(
            self.root / "tests/test_example.py",
            "import pytest\n\n"
            "pytestmark = pytest.mark.unit\n\n\n"
            "class TestExample:\n"
            "    pytestmark = [pytest.mark.slow, pytest.mark.integration]\n\n"
            "    def test_example(self):\n"
            "        pass\n",
        )

        with patch.object(check_agent_docs, "MANUAL_CATEGORY_MARKER_ALLOWLIST", frozenset()):
            check_agent_docs.check_manual_test_markers()

        self.assertEqual(
            check_agent_docs.errors,
            [
                "tests/test_example.py: TestExample introduce `pytest.mark.integration` manual; "
                "renombrá el test para usar auto-marking",
                "tests/test_example.py: <module> introduce `pytest.mark.unit` manual; "
                "renombrá el test para usar auto-marking",
            ],
        )

    def test_manual_markers_reject_every_way_of_assigning_pytestmark(self) -> None:
        assignments = {
            "tuple": "pytestmark = (pytest.mark.unit,)",
            "annotated": "pytestmark: list[pytest.MarkDecorator] = [pytest.mark.unit]",
            "augmented": "pytestmark = []\npytestmark += [pytest.mark.unit]",
            "concatenated": "pytestmark = [pytest.mark.unit] + COMMON",
            "unpacked": "pytestmark = [*COMMON, pytest.mark.unit]",
            "called": "pytestmark = pytest.mark.unit()",
            "conditional": "if CONDITION:\n    pytestmark = pytest.mark.unit",
        }

        with patch.object(check_agent_docs, "MANUAL_CATEGORY_MARKER_ALLOWLIST", frozenset()):
            for label, assignment in assignments.items():
                with self.subTest(label):
                    check_agent_docs.errors.clear()
                    _write(self.root / "tests/test_example.py", f"import pytest\n\n{assignment}\n")

                    check_agent_docs.check_manual_test_markers()

                    self.assertEqual(
                        check_agent_docs.errors,
                        [
                            "tests/test_example.py: <module> introduce `pytest.mark.unit` manual; "
                            "renombrá el test para usar auto-marking"
                        ],
                    )

    def test_manual_markers_accept_pytestmark_without_category(self) -> None:
        _write(
            self.root / "tests/test_example.py",
            "import pytest\n\n"
            'pytestmark = [pytest.mark.usefixtures("tmp_db"), pytest.mark.slow]\n\n\n'
            "def test_example():\n"
            # Variable local: pytest solo lee el `pytestmark` del módulo y de las clases.
            "    pytestmark = pytest.mark.unit\n",
        )

        with patch.object(check_agent_docs, "MANUAL_CATEGORY_MARKER_ALLOWLIST", frozenset()):
            check_agent_docs.check_manual_test_markers()

        self.assertEqual(check_agent_docs.errors, [])


class AgentHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.foreign_cwd = self.root / "nested/cwd"
        self.foreign_cwd.mkdir(parents=True)
        (self.root / "graphify-out").mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _copy_hook(self, name: str) -> Path:
        source = Path(__file__).resolve().parents[1] / ".claude/hooks" / name
        target = self.root / ".claude/hooks" / name
        _write(target, source.read_text(encoding="utf-8"))
        return target

    def _run_hook(self, hook: Path, payload: dict[str, object]) -> str:
        previous_cwd = Path.cwd()
        output = StringIO()
        try:
            os.chdir(self.foreign_cwd)
            with patch("sys.stdin", StringIO(json.dumps(payload))), redirect_stdout(output):
                runpy.run_path(str(hook), run_name="__main__")
        finally:
            os.chdir(previous_cwd)
        return output.getvalue()

    def test_edit_hook_marks_repository_graph_from_foreign_cwd(self) -> None:
        hook = self._copy_hook("pretooluse_edit_stale.py")

        self._run_hook(hook, {"tool_input": {"file_path": "services/example.py"}})

        self.assertTrue((self.root / "graphify-out/.graph_stale").is_file())
        self.assertFalse((self.foreign_cwd / "graphify-out/.graph_stale").exists())

    def test_search_hook_finds_repository_graph_from_foreign_cwd(self) -> None:
        hook = self._copy_hook("pretooluse_bash_grep_hint.py")
        _write(self.root / "graphify-out/graph.json", "{}")

        output = self._run_hook(hook, {"tool_input": {"command": "rg TODO"}})

        payload = json.loads(output)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("graphify query", context)

    def _otro_checkout(self) -> Path:
        """Un segundo checkout, como el worktree desde el que trabaja la sesión."""
        otro = self.root / "worktrees/otro"
        _write(otro / ".git", "gitdir: en-otra-parte\n")
        return otro

    def test_search_hook_calla_ante_un_filtro_de_tuberia(self) -> None:
        hook = self._copy_hook("pretooluse_bash_grep_hint.py")
        _write(self.root / "graphify-out/graph.json", "{}")

        for comando in ("git ls-files | grep py", "ls -la && cat x | grep -c foo", "echo listo"):
            with self.subTest(comando=comando):
                self.assertEqual(self._run_hook(hook, {"tool_input": {"command": comando}}), "")

    def test_search_hook_avisa_cuando_la_busqueda_va_tras_otro_comando(self) -> None:
        hook = self._copy_hook("pretooluse_bash_grep_hint.py")
        _write(self.root / "graphify-out/graph.json", "{}")

        for comando in ("cd web && grep -rn foo src", "git grep -n foo", "FOO=1 find . -name x"):
            with self.subTest(comando=comando):
                self.assertIn(
                    "graphify query", self._run_hook(hook, {"tool_input": {"command": comando}})
                )

    def test_search_hook_avisa_una_sola_vez_por_sesion(self) -> None:
        hook = self._copy_hook("pretooluse_bash_grep_hint.py")
        _write(self.root / "graphify-out/graph.json", "{}")
        sesion = f"test-{uuid.uuid4().hex}"
        marca = Path(tempfile.gettempdir()) / f"tf-pista-busqueda-{sesion}"
        self.addCleanup(marca.unlink, missing_ok=True)
        payload = {"tool_input": {"command": "rg TODO"}, "session_id": sesion}

        self.assertIn("graphify query", self._run_hook(hook, payload))
        self.assertEqual(self._run_hook(hook, payload), "")

    def test_search_hook_sin_grafo_propone_el_mapa_del_checkout_de_la_sesion(self) -> None:
        # El script vive en un checkout que sí tiene grafo; la sesión trabaja en
        # otro que no: manda el `cwd`, no la ubicación del fichero.
        hook = self._copy_hook("pretooluse_bash_grep_hint.py")
        _write(self.root / "graphify-out/graph.json", "{}")
        otro = self._otro_checkout()
        _write(otro / "scripts/code_map.py", "")

        output = self._run_hook(
            hook, {"tool_input": {"command": "rg TODO"}, "cwd": str(otro / "scripts")}
        )

        context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("scripts/code_map.py", context)
        self.assertNotIn("graphify query", context)

    def test_edit_hook_marca_el_checkout_del_fichero_editado(self) -> None:
        hook = self._copy_hook("pretooluse_edit_stale.py")
        otro = self._otro_checkout()
        (otro / "graphify-out").mkdir()

        self._run_hook(hook, {"tool_input": {"file_path": str(otro / "services/example.py")}})

        self.assertTrue((otro / "graphify-out/.graph_stale").is_file())
        self.assertFalse((self.root / "graphify-out/.graph_stale").exists())


class SessionStartContextoTests(unittest.TestCase):
    """`session_start_contexto.py`: qué le falta al checkout y qué hay en curso."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        base = Path(self.temp_dir.name)
        self.principal = base / "principal"
        self.worktree = base / "principal/.claude/worktrees/tarea"
        (self.principal / ".git").mkdir(parents=True)
        _write(self.worktree / ".git", "gitdir: ../../../.git/worktrees/tarea\n")
        _write(self.worktree / "web/package.json", "{}")
        self.prs: list[dict[str, object]] = []
        self.ramas = ""
        self.cli_graphify: str | None = None

    def _fake_run(self, cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if "--git-common-dir" in cmd:
            salida = str(self.principal / ".git")
        elif cmd[:3] == ["gh", "pr", "list"]:
            salida = json.dumps(self.prs)
        elif "for-each-ref" in cmd:
            salida = self.ramas
        elif "--abbrev-ref" in cmd:
            salida = "mi-rama"
        else:
            salida = "ok"
        return subprocess.CompletedProcess(cmd, 0, stdout=salida, stderr="")

    def _which(self, nombre: str) -> str | None:
        return {"gh": "/usr/bin/gh", "graphify": self.cli_graphify}.get(nombre)

    def _contexto(self) -> str:
        hook = Path(__file__).resolve().parents[1] / ".claude/hooks/session_start_contexto.py"
        output = StringIO()
        with (
            patch("sys.stdin", StringIO(json.dumps({"cwd": str(self.worktree / "web")}))),
            patch("subprocess.run", self._fake_run),
            patch("shutil.which", self._which),
            patch.dict(os.environ),
            redirect_stdout(output),
        ):
            # La suite corre con `ENV=dev` en el entorno; el hook lo vería y callaría.
            os.environ.pop("ENV", None)
            runpy.run_path(str(hook), run_name="__main__")
        if not output.getvalue():
            return ""
        return str(json.loads(output.getvalue())["hookSpecificOutput"]["additionalContext"])

    def test_dice_lo_que_le_falta_al_worktree_y_no_al_checkout_del_script(self) -> None:
        _write(self.principal / ".venv/bin/python", "")

        contexto = self._contexto()

        self.assertIn("no tiene `.venv`", contexto)
        self.assertIn((self.principal / ".venv/bin/python").as_posix(), contexto)
        self.assertIn("ENV=dev", contexto)
        self.assertIn("npm ci", contexto)

    def test_un_env_sin_la_variable_de_entorno_sigue_avisando(self) -> None:
        # El caso de una sesión remota: `session_start_pg.py` deja un `.env` con
        # solo la URL de tests, y `settings` sigue arrancando en `prod`.
        _write(self.worktree / ".env", "TEST_DATABASE_URL=postgresql://localhost/x\n")

        self.assertIn("ENV=dev", self._contexto())

    def test_sin_venv_pero_con_las_dependencias_instaladas_no_pide_instalarlas(self) -> None:
        # Sesión remota: `pip install` contra el Python del sistema, que es el
        # que lanza el hook (y esta suite: fastapi y pytest están).
        self.assertNotIn("Python:", self._contexto())

    def test_un_checkout_completo_no_anade_ruido(self) -> None:
        _write(self.worktree / ".venv/bin/python", "")
        _write(self.worktree / ".env", "ENV=dev\n")
        (self.worktree / "web/node_modules").mkdir()

        self.assertEqual(self._contexto(), "")

    def test_lista_los_pr_de_personas_y_las_ramas_recientes(self) -> None:
        self.prs = [
            {"number": 12, "title": "feat: cosa", "headRefName": "feat/cosa", "author": {}},
            {
                "number": 13,
                "title": "chore(deps): bump x",
                "headRefName": "dependabot/pip/x",
                "author": {"login": "app/dependabot"},
            },
        ]
        ahora = int(time.time())
        self.ramas = (
            f"feat/viva\t{ahora}\tfeat: en curso\n"
            f"mi-rama\t{ahora}\tfeat: la propia\n"
            f"feat/vieja\t{ahora - 30 * 24 * 3600}\tfeat: abandonada"
        )

        contexto = self._contexto()

        self.assertIn("#12 feat: cosa (feat/cosa)", contexto)
        self.assertNotIn("#13", contexto)
        self.assertIn("feat/viva: feat: en curso", contexto)
        self.assertNotIn("feat/vieja", contexto)
        self.assertNotIn("la propia", contexto)

    def test_siembra_el_grafo_del_checkout_principal_si_hay_cli(self) -> None:
        _write(self.principal / "graphify-out/graph.json", '{"nodes": []}')
        self.cli_graphify = "/usr/bin/graphify"

        contexto = self._contexto()

        self.assertEqual(
            (self.worktree / "graphify-out/graph.json").read_text(encoding="utf-8"),
            '{"nodes": []}',
        )
        self.assertIn("copiado del checkout principal", contexto)

    def test_sin_cli_no_copia_un_grafo_que_nadie_va_a_consultar(self) -> None:
        _write(self.principal / "graphify-out/graph.json", "{}")

        self._contexto()

        self.assertFalse((self.worktree / "graphify-out").exists())
