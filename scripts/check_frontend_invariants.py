"""Verifica los invariantes de integridad analítica del frontend (ADR-014).

Escanea ``web/src/**`` buscando los cinco anti-patrones documentados en
``docs/frontend-data-invariants.md``: el frontend **no fabrica analítica**, el
**estado de usuario es server-side** y **sin hardcode** que el backend/entorno
deben proveer.

Categorías detectadas (denylist de alto valor / bajo falso-positivo):

  localhost-url       ``http://localhost`` en datos renderizados (enlace roto en deploy)
  mock-data           ``const MOCK_`` / ``const LOCAL_`` alimentando render
  client-state        ``localStorage``/``STORAGE_KEY`` de reglas/alertas/watchlist
  large-limit         ``?limit=500|1000`` (agregación cliente sobre sample parcial)
  synthetic-graph     aristas de grafo derivadas de co-ocurrencia por CCAA

Modo por defecto: **warning** (exit 0) — reporta sin bloquear, para endurecer
categoría a categoría a medida que las páginas se migran (igual que el lint
progresivo del repo). Con ``--strict`` falla (exit 1) ante cualquier hallazgo no
permitido; ``--error-category CAT`` falla solo en esas categorías.

Allowlist por línea: añadí ``fdi-allow`` (o ``fdi-allow:categoria``) en un
comentario de la línea para justificar y excluir un hallazgo concreto.

Uso:
    python scripts/check_frontend_invariants.py
    python scripts/check_frontend_invariants.py --strict
    python scripts/check_frontend_invariants.py --error-category mock-data
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ── Configuración de escaneo ──────────────────────────────────────────────
DEFAULT_ROOT = Path("web/src")
SCAN_SUFFIXES: tuple[str, ...] = (".ts", ".tsx")
SKIP_DIR_PARTS: frozenset[str] = frozenset({"node_modules", ".next", "generated", "__tests__"})
SKIP_FILE_MARKERS: tuple[str, ...] = (".test.", ".spec.", ".stories.")
ALLOW_MARKER = "fdi-allow"

CATEGORIES: tuple[str, ...] = (
    "localhost-url",
    "mock-data",
    "client-state",
    "large-limit",
    "synthetic-graph",
)

# ── Patrones por categoría ────────────────────────────────────────────────
# localhost en una URL renderizable (no en comentario puro — ver _is_comment).
_RE_LOCALHOST = re.compile(r"https?://localhost|https?://127\.0\.0\.1")
# const MOCK_USERS = [...] / const LOCAL_FLAGS: FeatureFlag[] = [...]
_RE_MOCK = re.compile(r"\bconst\s+(?:MOCK_|LOCAL_)\w+\s*[:=]")
# localStorage / STORAGE_KEY con clave de reglas/alertas/watchlist.
_RE_CLIENT_STATE = re.compile(
    r"(?:localStorage\.\w+|getJSON|setJSON|STORAGE_KEY)\b"
    r"[^\n]*?(?:watchlist|rules|alert|destacad|favorit)",
    re.IGNORECASE,
)
# ?limit=500 / limit=1000 en una URL de fetch (sample agregado en cliente).
_RE_LARGE_LIMIT = re.compile(r"limit=(?:500|1000)\b")
# Grafo sintético: aristas por co-ocurrencia / CCAA compartida.
_RE_SYNTHETIC_GRAPH = re.compile(
    r"co-occurrence|comparten?\s+CCAA|share\s+CCAA|same\s+CCAA"
    r"|if\s+they\s+share\s+CCAA",
    re.IGNORECASE,
)

_PATTERNS: dict[str, re.Pattern[str]] = {
    "localhost-url": _RE_LOCALHOST,
    "mock-data": _RE_MOCK,
    "client-state": _RE_CLIENT_STATE,
    "large-limit": _RE_LARGE_LIMIT,
    "synthetic-graph": _RE_SYNTHETIC_GRAPH,
}

# Categorías que solo tienen sentido en comentarios (el marcador del anti-patrón
# suele vivir en un comentario): para estas NO saltamos las líneas-comentario.
_COMMENT_BEARING: frozenset[str] = frozenset({"synthetic-graph"})


@dataclass(frozen=True)
class Finding:
    path: Path
    line_no: int
    category: str
    snippet: str


def _iter_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in SCAN_SUFFIXES or not path.is_file():
            continue
        if SKIP_DIR_PARTS & set(path.parts):
            continue
        if any(marker in path.name for marker in SKIP_FILE_MARKERS):
            continue
        out.append(path)
    return out


def _is_comment(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(("//", "*", "/*"))


def scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return findings
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        # Allowlist: marcador en la propia línea o en la inmediatamente anterior
        # (patrón natural "comentario de justificación encima del hallazgo").
        prev = lines[idx - 2] if idx >= 2 else ""
        if ALLOW_MARKER in line or ALLOW_MARKER in prev:
            continue
        comment = _is_comment(line)
        for category, pattern in _PATTERNS.items():
            if comment and category not in _COMMENT_BEARING:
                continue
            if pattern.search(line):
                findings.append(Finding(path, idx, category, line.strip()[:120]))
    return findings


def _report(findings: list[Finding], root: Path) -> None:
    print(f"\n─── Invariantes de integridad analítica del frontend ({root}) ───")
    if not findings:
        print("[OK] Sin hallazgos. El frontend no fabrica analítica. ✅")
        return
    by_cat: dict[str, list[Finding]] = {c: [] for c in CATEGORIES}
    for f in findings:
        by_cat[f.category].append(f)
    for category in CATEGORIES:
        items = by_cat[category]
        if not items:
            continue
        print(f"\n  [{category}] {len(items)} hallazgo(s):")
        for f in items:
            rel = f.path.as_posix()
            print(f"    {rel}:{f.line_no}: {f.snippet}")
    print("\n─── Resumen ──────────────────────────────────────────────────")
    for category in CATEGORIES:
        print(f"  {category:<18} {len(by_cat[category]):>3}")
    print(f"  {'TOTAL':<18} {len(findings):>3}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Raíz a escanear")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Falla (exit 1) ante cualquier hallazgo no permitido",
    )
    parser.add_argument(
        "--error-category",
        action="append",
        default=[],
        choices=CATEGORIES,
        metavar="CAT",
        help="Falla solo en estas categorías (repetible)",
    )
    args = parser.parse_args()

    if not args.root.exists():
        print(f"[ERROR] No existe la raíz {args.root}")
        sys.exit(2)

    findings: list[Finding] = []
    for path in _iter_files(args.root):
        findings.extend(scan_file(path))

    _report(findings, args.root)

    fail_cats = set(args.error_category) or (set(CATEGORIES) if args.strict else set())
    blocking = [f for f in findings if f.category in fail_cats]
    if blocking:
        print(
            f"\n[FAIL] {len(blocking)} hallazgo(s) en categorías bloqueantes "
            f"({', '.join(sorted(fail_cats))})."
        )
        sys.exit(1)
    if findings:
        print(
            "\n[WARN] Hallazgos en modo aviso (no bloqueante). "
            "Migrá las páginas o justificá con 'fdi-allow'."
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
