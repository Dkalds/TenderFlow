"""One-off migration: agregar YAML frontmatter a los ADRs (docs/adr/*.md) para
que Obsidian Dataview pueda consultarlos (status, date, deciders, supersedes, related).

No toca el header en texto plano existente (Estado/Status, Fecha/Date, etc.) -
el frontmatter es una capa adicional para tooling, el body sigue siendo el
mismo documento legible.

Uso: python scripts/obsidian_adr_frontmatter.py [--dry-run]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
ADR_DIR = DOCS / "adr"
DRY_RUN = "--dry-run" in sys.argv

STATUS_MAP = {
    "accepted": "accepted",
    "aceptado": "accepted",
    "registrado": "proposed",
}


def extract_field(block: str, *labels: str) -> str | None:
    for label in labels:
        m = re.search(rf"\*\*{label}:?\*\*:?\s*(.+)", block, re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip(" \\")
    return None


def extract_wikilink_targets(block: str) -> list[str]:
    return re.findall(r"\[\[([^\|\]]+)\|", block)


def yaml_escape(value: str) -> str:
    value = value.replace('"', '\\"')
    return f'"{value}"'


def build_frontmatter(path: Path, text: str) -> str:
    # header block = desde el titulo hasta el primer '##' o '---' separador
    header_end = re.search(r"\n(?:## |---\n)", text)
    block = text[: header_end.start()] if header_end else text[:600]

    title_m = re.match(r"#\s*(ADR-\d{3,4})[:\s—-]*\s*(.*)", block)
    adr_id = title_m.group(1) if title_m else path.stem
    title = title_m.group(2).strip() if title_m else path.stem

    status_raw = extract_field(block, "Estado", "Status") or "unknown"
    status = STATUS_MAP.get(status_raw.split(" ")[0].strip("—").lower(), status_raw.lower())

    date = extract_field(block, "Fecha", "Date") or ""
    deciders = extract_field(block, "Deciders", "Autores") or ""
    supersedes_raw = extract_field(block, "Supersedes")
    related_targets = extract_wikilink_targets(block)

    supersedes_target = None
    if supersedes_raw:
        m = re.search(r"\[\[([^\|\]]+)\|", supersedes_raw)
        supersedes_target = m.group(1) if m else supersedes_raw

    lines = ["---", f"id: {adr_id}", f"title: {yaml_escape(title)}", f"status: {status}"]
    if date:
        lines.append(f"date: {date}")
    if deciders:
        lines.append(f"deciders: {yaml_escape(deciders)}")
    if supersedes_target:
        lines.append(f'supersedes: "[[{supersedes_target}]]"')
    if related_targets:
        lines.append("related:")
        for t in dict.fromkeys(related_targets):  # dedupe preservando orden
            lines.append(f'  - "[[{t}]]"')
    lines.append("tags: [adr]")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def process_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        return False  # ya tiene frontmatter

    frontmatter = build_frontmatter(path, text)
    new_text = frontmatter + "\n" + text

    if not DRY_RUN:
        path.write_text(new_text, encoding="utf-8")
    return True


def main() -> None:
    changed = []
    for path in sorted(ADR_DIR.glob("*.md")):
        if process_file(path):
            changed.append(path.name)

    print(f"Archivos modificados: {len(changed)}")
    for c in changed:
        print(f"  - {c}")
    if DRY_RUN:
        print("\n(dry-run, no se escribio nada)")


if __name__ == "__main__":
    main()
