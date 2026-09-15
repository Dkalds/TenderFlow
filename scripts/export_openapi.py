"""Exporta el schema OpenAPI de la API sin arrancar el servidor.

Importa ``api.app`` (el lifespan NO se ejecuta, así que no toca BD ni Redis) y
serializa ``app.openapi()`` de forma determinista (indent=2, sort_keys=True,
newline final) para que el fichero sea diffeable y el job CI ``codegen-drift``
pueda detectar drift con ``git diff --exit-code``.

Escribe **dos** ficheros:

* ``api/openapi.json`` — el spec completo, que es el que consume el codegen del
  frontend (``web/package.json::codegen:file``). Desde la revisión de salida al
  mercado lleva ``x-public: true`` en las operaciones con contrato.
* ``api/openapi-public.json`` — sólo esas operaciones, con los esquemas que
  alcanzan. **Es el que se le enseña a un integrador.** Sin él, las más de
  doscientas operaciones del completo quedan publicadas por igual y cambiar
  cualquiera pasa a romper a alguien; ver ``api/contrato_publico.py``.

Uso::

    python scripts/export_openapi.py [ruta-destino]

El segundo fichero se escribe junto al primero, con el sufijo ``-public``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _volcar(schema: dict[str, object], dest: Path) -> None:
    """Escritura determinista: mismo orden y mismo final de línea siempre."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(schema, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def export_openapi(dest: Path) -> dict[str, object]:
    """Escribe el spec completo y el público. Devuelve el completo, ya marcado.

    La firma no cambió al añadir el segundo fichero —sigue devolviendo el
    schema— porque tres llamantes dependen de ella (``check_contract_fixtures``
    y dos tests): cuántas operaciones quedaron marcadas se cuenta sobre lo que
    devuelve, con ``operaciones_publicas``, y no hace falta un segundo valor de
    retorno que rompa a todo el mundo.
    """
    sys.path.insert(0, str(_REPO_ROOT))
    from api.app import app
    from api.contrato_publico import filtrar_publico, marcar_publicas

    schema: dict[str, object] = app.openapi()
    marcar_publicas(schema)
    _volcar(schema, dest)
    _volcar(filtrar_publico(schema), dest.with_name(f"{dest.stem}-public{dest.suffix}"))
    return schema


def operaciones_publicas(schema: dict[str, object]) -> int:
    """Cuántas operaciones del schema llevan la marca ``x-public``."""
    from api.contrato_publico import EXTENSION

    rutas = schema.get("paths")
    if not isinstance(rutas, dict):
        return 0
    return sum(
        1
        for operaciones in rutas.values()
        if isinstance(operaciones, dict)
        for operacion in operaciones.values()
        if isinstance(operacion, dict) and operacion.get(EXTENSION) is True
    )


def main() -> int:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else _REPO_ROOT / "api" / "openapi.json"
    schema = export_openapi(dest)
    publicas = operaciones_publicas(schema)
    paths = schema.get("paths")
    n_paths = len(paths) if isinstance(paths, dict) else 0
    if n_paths == 0:
        print(f"ERROR: schema sin paths — no se escribió nada útil en {dest}", file=sys.stderr)
        return 1
    if publicas == 0:
        # Un público vacío no es un fichero pequeño: es un contrato borrado.
        print(
            "ERROR: ninguna operación quedó marcada como pública. Las rutas de "
            "`api/contrato_publico.py` no casan con las de la app.",
            file=sys.stderr,
        )
        return 1
    publico = dest.with_name(f"{dest.stem}-public{dest.suffix}")
    print(f"OpenAPI exportado: {dest} ({n_paths} paths)")
    print(f"Contrato público: {publico} ({publicas} operaciones)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
