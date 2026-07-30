"""Convierte referencias ADR-NNN/RFC-NNN y links relativos markdown dentro de
docs/ a wikilinks de Obsidian ([[archivo|texto]]).

Nunca toca el *target* de un link markdown, ni código inline, ni bloques de
código: una corrida previa reescribió el ID dentro de `](adr/ADR-004-....md)` y
dejó ocho links roto (wikilink anidado dentro del target, que no resuelve ni en
Obsidian ni en GitHub). `make check-agent-docs` falla si reaparecen.

Uso: python scripts/obsidian_wikilink.py [--dry-run]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
DRY_RUN = "--dry-run" in sys.argv

SKIP_DIRS = {".obsidian", "rfc/README.md"}


def build_id_map() -> dict[str, str]:
    """Mapea 'ADR-004' / 'RFC-086' -> stem del archivo (para [[stem]])."""
    id_map: dict[str, str] = {}

    for f in (DOCS / "adr").glob("*.md"):
        stem = f.stem
        m = re.match(r"^(?:ADR-)?(\d{3,4})", stem)
        if not m:
            continue
        num = m.group(1)
        # normaliza a 3 digitos si el original tenia 4 con ceros (0011 -> mantener tal cual se referencia en texto)
        candidates = {f"ADR-{num}", f"ADR-{num.lstrip('0').zfill(3)}"}
        for c in candidates:
            id_map[c] = stem

    for f in (DOCS / "rfc").glob("*.md"):
        stem = f.stem
        m = re.match(r"^(\d{3})-", stem)
        if not m:
            continue
        num = m.group(1)
        id_map[f"RFC-{num}"] = stem

    return id_map


def convert_relative_links(text: str) -> str:
    """[texto](../rfc/xxx.md) o [texto](../adr/xxx.md) -> [[xxx|texto]]"""

    def repl(match: re.Match) -> str:
        label, path = match.group(1), match.group(2)
        stem = Path(path.split("#")[0]).stem
        return f"[[{stem}|{label}]]"

    pattern = re.compile(r"\[([^\]\[]+)\]\((\.\./(?:adr|rfc)/[^)\s]+\.md)\)")
    return pattern.sub(repl, text)


# Regiones donde un ID nunca debe reescribirse: target de link markdown, código
# inline y bloques de código. El orden importa: los fences primero.
PROTECTED = re.compile(r"```.*?```|``[^`]*``|`[^`\n]*`|\]\([^)\n]*\)", re.DOTALL)
_SENTINEL = "\x00{}\x00"


def mask_protected(text: str) -> tuple[str, list[str]]:
    """Sustituye las regiones protegidas por centinelas irreemplazables."""
    spans: list[str] = []

    def repl(match: re.Match) -> str:
        spans.append(match.group(0))
        return _SENTINEL.format(len(spans) - 1)

    return PROTECTED.sub(repl, text), spans


def unmask_protected(text: str, spans: list[str]) -> str:
    for i, span in enumerate(spans):
        text = text.replace(_SENTINEL.format(i), span)
    return text


def convert_bare_ids(text: str, id_map: dict[str, str], self_stem: str | None = None) -> str:
    text, protected = mask_protected(text)
    # ordenar claves mas largas primero para evitar solapes (ADR-0011 antes de ADR-001)
    for key in sorted(id_map, key=len, reverse=True):
        stem = id_map[key]
        if stem == self_stem:
            continue  # no auto-linkear el propio documento
        # no tocar si ya esta dentro de un wikilink [[...key...]] o ya seguido de |
        pattern = re.compile(rf"(?<!\[)(?<!\[\[)\b{re.escape(key)}\b(?!\]\])(?!\|)")

        def repl(match: re.Match, stem=stem, key=key, text=text) -> str:
            start = match.start()
            # si esta inmediatamente precedido por '[[' (con posible texto entremedio corto), skip
            prefix = text[max(0, start - 2) : start]
            if prefix == "[[":
                return match.group(0)
            return f"[[{stem}|{key}]]"

        text = pattern.sub(repl, text)
    return unmask_protected(text, protected)


def already_wikilinked(text: str, key: str) -> bool:
    return f"|{key}]]" in text or f"[[{key}]]" in text


def process_file(path: Path, id_map: dict[str, str]) -> bool:
    original = path.read_text(encoding="utf-8")
    text = original

    text = convert_relative_links(text)
    text = convert_bare_ids(text, id_map, self_stem=path.stem)

    if text != original:
        if not DRY_RUN:
            path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    id_map = build_id_map()
    print(f"IDs mapeados: {len(id_map)}")

    changed = []
    for path in DOCS.rglob("*.md"):
        if ".obsidian" in path.parts:
            continue
        if process_file(path, id_map):
            changed.append(path.relative_to(DOCS.parent))

    print(f"Archivos modificados: {len(changed)}")
    for c in changed:
        print(f"  - {c}")

    if DRY_RUN:
        print("\n(dry-run, no se escribio nada)")


if __name__ == "__main__":
    main()
