"""Recalcula `verifiedHash` en skills-lock.json para cada skill instalado.

Correlo tras instalar, actualizar o quitar deliberadamente un skill de
`.agents/skills/` / `.claude/skills/`. `check_agent_docs.py::check_skill_trees`
exige que ambos árboles sean idénticos y que el hash coincida con el contenido
real — si cambiás un SKILL.md vendored y no corrés este script, el checker
falla con "cambió de contenido sin actualizar `verifiedHash`".

No reproduce el `computedHash` que escribe la CLI externa `skills add` (algoritmo
propietario no documentado, no reconstruible localmente); `verifiedHash` es un
campo propio, calculado y verificado enteramente por este repo.

Uso: python scripts/update_skills_lock_hashes.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_SKILLS = ROOT / ".agents/skills"
LOCK_PATH = ROOT / "skills-lock.json"


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def combined_hash(file_hashes: dict[str, str]) -> str:
    manifest = "".join(f"{rel}:{file_hashes[rel]}\n" for rel in sorted(file_hashes))
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def main() -> int:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    skills = lock.get("skills", {})
    updated = 0
    for name in sorted(skills):
        skill_dir = AGENTS_SKILLS / name
        if not (skill_dir / "SKILL.md").exists():
            print(f"WARN  {name}: no está instalado en .agents/skills/, se omite")
            continue
        new_hash = combined_hash(tree_hashes(skill_dir))
        if skills[name].get("verifiedHash") != new_hash:
            skills[name]["verifiedHash"] = new_hash
            updated += 1
    LOCK_PATH.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"verifiedHash actualizado para {updated} skill/s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
