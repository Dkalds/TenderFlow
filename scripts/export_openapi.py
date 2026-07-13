"""Exporta el schema OpenAPI de la API a ``api/openapi.json`` sin arrancar el servidor.

Importa ``api.app`` (el lifespan NO se ejecuta, así que no toca BD ni Redis) y
serializa ``app.openapi()`` de forma determinista (indent=2, sort_keys=True,
newline final) para que el fichero sea diffeable y el job CI ``codegen-drift``
pueda detectar drift con ``git diff --exit-code``.

Uso::

    python scripts/export_openapi.py [ruta-destino]

Por defecto escribe en ``api/openapi.json`` (la ruta que consume
``web/package.json::codegen:file``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def export_openapi(dest: Path) -> dict[str, object]:
    """Genera el schema OpenAPI y lo escribe en ``dest``. Devuelve el schema."""
    sys.path.insert(0, str(_REPO_ROOT))
    from api.app import app

    schema: dict[str, object] = app.openapi()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(schema, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    return schema


def main() -> int:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else _REPO_ROOT / "api" / "openapi.json"
    schema = export_openapi(dest)
    paths = schema.get("paths")
    n_paths = len(paths) if isinstance(paths, dict) else 0
    if n_paths == 0:
        print(f"ERROR: schema sin paths — no se escribió nada útil en {dest}", file=sys.stderr)
        return 1
    print(f"OpenAPI exportado: {dest} ({n_paths} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
