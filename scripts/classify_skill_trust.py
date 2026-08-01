"""Asigna `trust` (first-party/community) a cada skill en skills-lock.json.

`trust` es una clasificación propia del repo, no un dato que provea la CLI
externa de instalación. `first-party` significa que el `source` (org/repo de
GitHub) pertenece al vendor oficial de la herramienta que documenta el skill
(p.ej. `anthropics/*` para skills de Anthropic, `vercel-labs/*` para Vercel,
`upstash/*` para Upstash, `supabase/*` para Supabase). Todo lo demás
(mantenedores individuales, agregadores de terceros como
`wshobson/agents` o `pluginagentmarketplace/*`) es `community`: puede ser
igual de útil, pero no tiene el mismo respaldo de mantenimiento/seguridad que
un repo del propio vendor.

Correlo tras instalar un skill nuevo (`check_agent_docs.py::check_skill_trees`
falla si a algún skill del lock le falta `trust`). No pisa una clasificación
ya presente — para reclasificar un skill existente, editá `skills-lock.json`
a mano.

Uso: python scripts/classify_skill_trust.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK_PATH = ROOT / "skills-lock.json"

FIRST_PARTY_ORGS = frozenset({"anthropics", "vercel-labs", "upstash", "supabase"})


def classify(source: str) -> str:
    org = source.split("/", 1)[0]
    return "first-party" if org in FIRST_PARTY_ORGS else "community"


def main() -> int:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    skills = lock.get("skills", {})
    updated = 0
    for name in sorted(skills):
        if "trust" in skills[name]:
            continue
        skills[name]["trust"] = classify(skills[name]["source"])
        updated += 1
    LOCK_PATH.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"trust asignado para {updated} skill/s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
