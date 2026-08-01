"""Tests for deterministic agent-customization validation."""

from __future__ import annotations

import json
import os
import runpy
import tempfile
import unittest
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
        json.dumps(
            {"skills": {"demo": {"verifiedHash": verified_hash, "trust": "community"}}}
        ),
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
            any(
                "cambió de contenido sin actualizar" in error
                for error in check_agent_docs.errors
            )
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
        allowlist = frozenset(
            {("tests/test_integration_e2e.py", "integration", "TestLegacy")}
        )

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
        self.assertIn("committed artifacts", context)