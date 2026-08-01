#!/usr/bin/env python3
"""Genera ``docs/skills-inventory.md`` a partir de ``skills-lock.json``.

Misma regla que `scripts/gen_status.py`: si un hecho se puede calcular, no se
escribe a mano. El inventario de skills (nombre, origen, nivel de confianza,
descripción) se deriva de `skills-lock.json` y del frontmatter de cada
`SKILL.md` en `.agents/skills/`, así que no puede desincronizarse del lock ni
de `scripts/classify_skill_trust.py`.

Uso::

    python scripts/gen_skills_inventory.py            # escribe docs/skills-inventory.md
    python scripts/gen_skills_inventory.py --check     # falla si el fichero está desfasado
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "skills-lock.json"
AGENTS_SKILLS = ROOT / ".agents/skills"
OUT = ROOT / "docs" / "skills-inventory.md"

_MARKER = "<!-- generado por scripts/gen_skills_inventory.py — no editar a mano -->"

FRONTMATTER_DESCRIPTION = re.compile(r"^description:\s*[\"']?(.+?)[\"']?\s*$", re.MULTILINE)


def _description(name: str) -> str:
    """Primera línea de `description:` del frontmatter de SKILL.md, si existe."""
    skill_md = AGENTS_SKILLS / name / "SKILL.md"
    if not skill_md.exists():
        return "—"
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    match = FRONTMATTER_DESCRIPTION.search(text)
    if not match:
        return "—"
    desc = match.group(1).strip()
    if len(desc) > 140:
        desc = desc[:137].rstrip() + "…"
    return desc.replace("|", "\\|")


def render() -> str:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    skills: dict[str, dict[str, str]] = lock["skills"]

    lines = [
        _MARKER,
        "",
        "# Inventario de skills",
        "",
        "Derivado de [`skills-lock.json`](../skills-lock.json) y el frontmatter de cada",
        "`SKILL.md` en [`.agents/skills/`](../.agents/skills/). Regenerar con",
        "`python scripts/gen_skills_inventory.py` tras instalar/actualizar un skill.",
        "Ver AGENTS.md §7 para qué significa `trust`.",
        "",
        f"Total: {len(skills)} skills.",
        "",
        "| Skill | Trust | Source | Descripción |",
        "| --- | --- | --- | --- |",
    ]
    for name in sorted(skills, key=lambda n: (skills[n].get("trust", ""), n)):
        entry = skills[name]
        trust = entry.get("trust", "?")
        source = entry.get("source", "?")
        lines.append(f"| `{name}` | {trust} | {source} | {_description(name)} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    content = render()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != content:
            print("docs/skills-inventory.md está desfasado; corré scripts/gen_skills_inventory.py")
            return 1
        print("docs/skills-inventory.md al día.")
        return 0
    OUT.write_text(content, encoding="utf-8")
    print(
        f"Escrito {OUT.relative_to(ROOT)} ({len(json.loads(LOCK.read_text(encoding='utf-8'))['skills'])} skills)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
