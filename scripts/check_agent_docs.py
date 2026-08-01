"""Verifica que las instrucciones de agentes describan el repo real.

Valida, sobre `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`,
`docs/AGENT_PLAYBOOK.md`, `docs/graphify-first.md` y las configs de cada
herramienta (`.claude/`, `.agents/`, `.codex/`, `.opencode/`):

1. Todo `make <target>` citado existe en el Makefile.
2. Todo slash-command citado existe en `.claude/commands/`.
3. Los skills nombrados en CLAUDE.md existen en `.claude/skills/` y son
   invocables por el modelo.
4. `.claude/skills/` y `.agents/skills/` contienen todo lo que declara
   `skills-lock.json` (los dos árboles no divergen) y su `verifiedHash`
   coincide con el contenido instalado (detecta tamperizado o un lock
   desactualizado; ver `scripts/update_skills_lock_hashes.py`). Cada skill
   también declara `trust` (`first-party`/`community`; ver
   `scripts/classify_skill_trust.py`).
5. Toda ruta del repo citada entre backticks o como link markdown existe.
6. Los hooks apuntan a scripts existentes y sin rutas absolutas de una máquina.
7. Los comandos de `.claude/commands/` y sus copias
   `.agents/skills/source-command-*/` no divergen.
8. No quedan wikilinks de Obsidian anidados dentro de links markdown.
9. Los hooks Claude/Codex son equivalentes y los plugins OpenCode existen.
10. No se introducen markers pytest manuales de categoría fuera de las
    excepciones históricas congeladas.

Uso: python scripts/check_agent_docs.py [--verbose]
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INSTRUCTION_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    "web/AGENTS.md",
    ".github/copilot-instructions.md",
    "docs/AGENT_PLAYBOOK.md",
    "docs/graphify-first.md",
    "docs/contributor-checklist.md",
    "docs/windows-happy-path.md",
    ".agents/rules/graphify.md",
    ".agents/workflows/graphify.md",
]

COMMANDS_DIR = ROOT / ".claude/commands"
CLAUDE_SKILLS = ROOT / ".claude/skills"
AGENTS_SKILLS = ROOT / ".agents/skills"
AGENTS_SKILL_PREFIX_ALLOWLIST = ("source-command-",)

VALID_TRUST_LEVELS = frozenset({"first-party", "community"})

CATEGORY_MARKERS = frozenset({"unit", "integration", "e2e", "property", "load"})
MANUAL_CATEGORY_MARKER_ALLOWLIST = frozenset(
    {
        ("tests/test_integration_e2e.py", "integration", "TestE2EPipelineToDatabase"),
        ("tests/test_integration_e2e.py", "integration", "TestE2EHistoryTracking"),
        ("tests/test_integration_e2e.py", "integration", "TestE2EDataLoader"),
        ("tests/test_integration_e2e.py", "integration", "TestE2EFilters"),
        ("tests/test_integration_e2e.py", "integration", "TestE2EKpiPrecompute"),
        ("tests/test_integration_e2e.py", "integration", "TestE2ERateLimiting"),
    }
)

# Tokens que parecen slash-command pero no lo son.
SLASH_ALLOWLIST = {"/api", "/ask", "/me", "/competitive", "/analytics", "/graphify"}

# Rutas citadas que son ejemplos o plantillas, no archivos reales.
PATH_ALLOWLIST = {
    "graphify-out/wiki/index.md",  # lo genera el CLI, opcional
    "graphify-out/wiki/",
    "graphify-out/GRAPH_REPORT.md",
    "graphify-out/.graph_stale",
    "graphify-out/graph.json",
}

ABSOLUTE_PATH_PATTERNS = [
    re.compile(r"[A-Za-z]:\\\\"),  # C:\... escapado en JSON
    re.compile(r"[A-Za-z]:\\[A-Za-z]"),  # C:\...
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
]

BACKTICK = re.compile(r"`([^`\n]+)`")
LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")
MAKE_CALL = re.compile(r"\bmake\s+([a-z][a-z0-9-]*)(?![a-z0-9*-])")
HOOK_SCRIPT = re.compile(r"(\.claude|\.codex)/hooks/([\w-]+\.py)")
FRONTMATTER_NAME = re.compile(r"^name:\s*[\"']?([^\"'\n]+)[\"']?", re.MULTILINE)

errors: list[str] = []
warnings: list[str] = []


def fail(where: str, msg: str) -> None:
    errors.append(f"{where}: {msg}")


def warn(where: str, msg: str) -> None:
    warnings.append(f"{where}: {msg}")


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def make_targets() -> set[str]:
    text = read("Makefile")
    return set(re.findall(r"^([a-z][a-z0-9-]*):", text, re.MULTILINE))


def looks_like_path(token: str) -> bool:
    if any(c in token for c in "*?{}<>$ |"):
        return False
    if token.startswith(("http", "mailto:", "#")):
        return False
    # Dependencias instaladas: existen o no según el entorno, no según el doc.
    if token.startswith("node_modules/") or "/node_modules/" in token:
        return False
    # `competitive/`, `wiki/`: un solo segmento, se lee relativo al paquete que
    # menciona la prosa alrededor. No es una ruta resoluble desde la raíz.
    if "/" not in token.rstrip("/"):
        return False
    return bool(re.search(r"\.[a-z]{1,5}$", token) or token.endswith("/"))


def check_make_targets(targets: set[str]) -> None:
    sources = [
        *INSTRUCTION_FILES,
        *(f".claude/commands/{p.name}" for p in sorted(COMMANDS_DIR.glob("*.md"))),
    ]
    for rel in sources:
        for target in set(MAKE_CALL.findall(read(rel))):
            if target not in targets:
                fail(rel, f"cita `make {target}`, que no existe en el Makefile")


def check_slash_commands() -> None:
    available = {f"/{p.stem}" for p in COMMANDS_DIR.glob("*.md")}
    for rel in INSTRUCTION_FILES:
        for token in set(BACKTICK.findall(read(rel))):
            name = token.split()[0]
            if not re.fullmatch(r"/[a-z][a-z0-9-]*", name):
                continue
            if name in SLASH_ALLOWLIST or name in available:
                continue
            fail(rel, f"cita el slash-command `{name}`, que no existe en .claude/commands/")


def skill_is_model_invocable(skill_dir: Path) -> bool:
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    head = text.split("---", 2)[1] if text.startswith("---") else ""
    return "disable-model-invocation: true" not in head


def tree_hashes(root: Path) -> dict[str, str]:
    """Return stable SHA-256 hashes for every file below ``root``."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def combined_hash(file_hashes: dict[str, str]) -> str:
    """Return one deterministic hash for a skill tree from its per-file hashes.

    Self-computed and self-verified: unrelated to the `computedHash` field that
    the external `skills add` CLI writes at install time (undocumented,
    proprietary algorithm we cannot reproduce). This one we generate and check
    ourselves via `scripts/update_skills_lock_hashes.py`.
    """
    manifest = "".join(f"{rel}:{file_hashes[rel]}\n" for rel in sorted(file_hashes))
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def check_claude_skills() -> None:
    """Valida los nombres de skill citados en frases que hablan de skills."""
    sentences = [s for s in re.split(r"(?<=[.:])\s", read("CLAUDE.md")) if "skill" in s.lower()]
    if not sentences:
        warn("CLAUDE.md", "no menciona skills; no se validó ningún nombre")
        return
    for sentence in sentences:
        # Los skills de referencia se nombran en la frase que explica por qué no
        # se invocan; ahí `disable-model-invocation: true` es esperado.
        reference_only = "disable-model-invocation" in sentence
        # Una frase que afirma que un skill NO existe se valida al revés: si
        # alguien lo crea, la afirmación pasa a ser falsa y hay que actualizarla.
        negated = "no existe" in sentence.lower()
        for token in BACKTICK.findall(sentence):
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", token):
                continue
            skill = CLAUDE_SKILLS / token
            exists = (skill / "SKILL.md").exists()
            if negated:
                if exists:
                    fail(
                        "CLAUDE.md",
                        f"afirma que el skill `{token}` no existe, pero .claude/skills/{token} sí está",
                    )
            elif not exists:
                fail("CLAUDE.md", f"nombra el skill `{token}`, que no existe en .claude/skills/")
            elif not reference_only and not skill_is_model_invocable(skill):
                fail(
                    "CLAUDE.md",
                    f"presenta `{token}` como invocable, pero tiene disable-model-invocation: true",
                )


def check_skill_trees() -> None:
    lock_path = ROOT / "skills-lock.json"
    if not lock_path.exists():
        return
    lock = json.loads(lock_path.read_text(encoding="utf-8")).get("skills", {})
    locked_names = set(lock)
    for name in sorted(lock):
        skill_dirs = [tree / name for tree in (CLAUDE_SKILLS, AGENTS_SKILLS)]
        for skill_dir in skill_dirs:
            if not (skill_dir / "SKILL.md").exists():
                fail(
                    "skills-lock.json",
                    f"declara `{name}` pero falta en {skill_dir.parent.relative_to(ROOT)}/ "
                    "(los dos árboles deben coincidir)",
                )
        if all((skill_dir / "SKILL.md").exists() for skill_dir in skill_dirs):
            claude_hashes, agents_hashes = (tree_hashes(skill_dir) for skill_dir in skill_dirs)
            if claude_hashes != agents_hashes:
                differing = sorted(
                    path
                    for path in claude_hashes.keys() | agents_hashes.keys()
                    if claude_hashes.get(path) != agents_hashes.get(path)
                )
                fail(
                    "skills-lock.json",
                    f"el skill `{name}` diverge entre .claude/skills y .agents/skills "
                    f"({len(differing)} archivo/s), p.ej.: {differing[0]}",
                )
            verified = combined_hash(claude_hashes)
            locked_hash = lock[name].get("verifiedHash")
            if locked_hash is None:
                fail(
                    "skills-lock.json",
                    f"`{name}` no tiene `verifiedHash`; corré "
                    "`python scripts/update_skills_lock_hashes.py`",
                )
            elif locked_hash != verified:
                fail(
                    "skills-lock.json",
                    f"`{name}` cambió de contenido sin actualizar `verifiedHash` en el lock "
                    "(revisá el cambio y corré `python scripts/update_skills_lock_hashes.py`)",
                )
            trust = lock[name].get("trust")
            if trust is None:
                fail(
                    "skills-lock.json",
                    f"`{name}` no tiene `trust` (first-party/community); corré "
                    "`python scripts/classify_skill_trust.py`",
                )
            elif trust not in VALID_TRUST_LEVELS:
                fail(
                    "skills-lock.json",
                    f"`{name}` tiene `trust` inválido ({trust!r}); debe ser "
                    "first-party o community",
                )
    for tree in (CLAUDE_SKILLS, AGENTS_SKILLS):
        installed = {path.parent.name for path in tree.glob("*/SKILL.md")}
        extras = installed - locked_names
        if tree == AGENTS_SKILLS:
            extras = {
                name for name in extras if not name.startswith(AGENTS_SKILL_PREFIX_ALLOWLIST)
            }
        for name in sorted(extras):
            fail(
                "skills-lock.json",
                f"{tree.relative_to(ROOT)}/{name} no está declarado en el lock "
                "ni es un skill local permitido",
            )
    reported: set[str] = set()
    for tree in (CLAUDE_SKILLS, AGENTS_SKILLS):
        for skill in sorted(tree.glob("*/SKILL.md")):
            declared = FRONTMATTER_NAME.search(skill.read_text(encoding="utf-8", errors="replace"))
            name = declared.group(1).strip() if declared else skill.parent.name
            if name != skill.parent.name and skill.parent.name not in reported:
                reported.add(skill.parent.name)
                warn(
                    f"skills/{skill.parent.name}",
                    f"frontmatter name '{name}' != directorio (vendored upstream; el modelo lo indexa por frontmatter)",
                )


def check_paths() -> None:
    for rel in INSTRUCTION_FILES:
        text = read(rel)
        base = (ROOT / rel).parent
        for token in set(BACKTICK.findall(text)):
            token = token.strip().rstrip(",.;:")
            if not looks_like_path(token) or token in PATH_ALLOWLIST:
                continue
            if not (ROOT / token).exists():
                fail(rel, f"cita la ruta `{token}`, que no existe")
        for target in set(LINK_TARGET.findall(text)):
            target = target.split("#")[0]
            if not target or target.startswith(("http", "mailto:")) or "*" in target:
                continue
            if not (base / target).exists():
                fail(rel, f"link roto: {target}")


def check_hooks_and_absolute_paths() -> None:
    configs = [
        ".claude/settings.json",
        ".codex/hooks.json",
        ".opencode/opencode.json",
        *INSTRUCTION_FILES,
    ]
    for rel in configs:
        text = read(rel)
        if not text:
            continue
        for pattern in ABSOLUTE_PATH_PATTERNS:
            if pattern.search(text):
                fail(
                    rel,
                    "contiene una ruta absoluta de una máquina concreta (usá la variable de proyecto)",
                )
                break
        for tool_dir, script in set(HOOK_SCRIPT.findall(text)):
            if not (ROOT / tool_dir / "hooks" / script).exists():
                fail(rel, f"referencia el hook {tool_dir}/hooks/{script}, que no existe")
    for rel in (".claude/settings.json", ".codex/hooks.json"):
        text = read(rel)
        if text and "python" in text and "hooks/" not in text:
            warn(rel, "define hooks sin apuntar a .../hooks/*.py")


def check_hook_parity() -> None:
    claude_files = {path.name: path for path in (ROOT / ".claude/hooks").glob("*.py")}
    codex_files = {path.name: path for path in (ROOT / ".codex/hooks").glob("*.py")}
    for name in sorted(claude_files.keys() | codex_files.keys()):
        if name not in claude_files or name not in codex_files:
            fail("hooks", f"el hook `{name}` no existe en ambos adaptadores Claude/Codex")
            continue
        if claude_files[name].read_bytes() != codex_files[name].read_bytes():
            fail("hooks", f"el hook `{name}` diverge entre .claude/hooks y .codex/hooks")


def check_opencode_plugins() -> None:
    config_path = ROOT / ".opencode/opencode.json"
    if not config_path.exists():
        return
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(".opencode/opencode.json", f"JSON inválido: {exc.msg}")
        return
    plugins = config.get("plugin", [])
    if not isinstance(plugins, list):
        fail(".opencode/opencode.json", "`plugin` debe ser una lista")
        return
    for plugin in plugins:
        if not isinstance(plugin, str) or not (ROOT / plugin).is_file():
            fail(".opencode/opencode.json", f"referencia un plugin inexistente: {plugin!r}")


def check_command_copies() -> None:
    for command in sorted(COMMANDS_DIR.glob("*.md")):
        copy = AGENTS_SKILLS / f"source-command-{command.stem}/SKILL.md"
        if not copy.exists():
            fail(
                command.relative_to(ROOT).as_posix(),
                f"falta la copia portable {copy.relative_to(ROOT).as_posix()}",
            )
            continue
        body = command.read_text(encoding="utf-8").split("---", 2)[-1].strip()
        copy_text = copy.read_text(encoding="utf-8")
        marker = "## Command Template"
        if marker not in copy_text:
            fail(
                copy.relative_to(ROOT).as_posix(),
                f"no contiene la sección canónica `{marker}`",
            )
            continue
        copy_body = copy_text.split(marker, 1)[1].strip()
        if copy_body != body:
            fail(
                copy.relative_to(ROOT).as_posix(),
                f"divergió de {command.relative_to(ROOT).as_posix()} "
                "(el cuerpo debe coincidir exactamente)",
            )


def check_nested_wikilinks() -> None:
    files = [ROOT / rel for rel in INSTRUCTION_FILES] + sorted((ROOT / "docs").rglob("*.md"))
    for path in files:
        if not path.exists():
            continue
        for target in LINK_TARGET.findall(path.read_text(encoding="utf-8")):
            if "[[" in target:
                fail(
                    str(path.relative_to(ROOT)),
                    f"wikilink anidado dentro de un link markdown: {target}",
                )


def _category_marker(decorator: ast.expr) -> str | None:
    expression = decorator.func if isinstance(decorator, ast.Call) else decorator
    if not isinstance(expression, ast.Attribute) or expression.attr not in CATEGORY_MARKERS:
        return None
    mark = expression.value
    if not isinstance(mark, ast.Attribute) or mark.attr != "mark":
        return None
    if not isinstance(mark.value, ast.Name) or mark.value.id != "pytest":
        return None
    return expression.attr


def check_manual_test_markers() -> None:
    found: set[tuple[str, str, str]] = set()
    tests_dir = ROOT / "tests"
    if not tests_dir.exists():
        return
    for path in sorted(tests_dir.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            fail(rel, f"no se pudo analizar para markers manuales: {exc.msg}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                marker = _category_marker(decorator)
                if marker is not None:
                    found.add((rel, marker, node.name))

    for rel, marker, scope in sorted(found - MANUAL_CATEGORY_MARKER_ALLOWLIST):
        fail(
            rel,
            f"{scope} introduce `pytest.mark.{marker}` manual; renombrá el test para usar auto-marking",
        )
    for rel, marker, scope in sorted(MANUAL_CATEGORY_MARKER_ALLOWLIST - found):
        fail(
            "marker allowlist",
            f"la excepción `{rel}:{scope}` (`{marker}`) ya no existe; eliminála del ratchet",
        )


def main() -> int:
    verbose = "--verbose" in sys.argv
    targets = make_targets()
    check_make_targets(targets)
    check_slash_commands()
    check_claude_skills()
    check_skill_trees()
    check_paths()
    check_hooks_and_absolute_paths()
    check_hook_parity()
    check_opencode_plugins()
    check_command_copies()
    check_nested_wikilinks()
    check_manual_test_markers()

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")

    if errors:
        print(f"\n{len(errors)} problema/s en las instrucciones de agentes.")
        return 1
    if verbose:
        print(f"Targets del Makefile conocidos: {len(targets)}")
    print(f"Instrucciones de agentes consistentes ({len(warnings)} warning/s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
