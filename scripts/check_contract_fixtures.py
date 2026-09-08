"""Valida los fixtures del frontend contra el esquema OpenAPI real (C8.3).

`tests/test_pursuits_api_contract.py` y `tests/test_contract_dto.py` fijan
códigos de error y forma de DTO **del lado del backend**. Ninguno mira lo que el
frontend cree que recibe: los tests de `web/src/hooks` construyen a mano el JSON
que devuelve el `fetch` doblado, y ese JSON puede tener un campo que la API no
manda —o faltarle uno que sí— sin que nada falle. El test pasa; producción no.

Este script cierra ese hueco: cada fixture declara su operación en
`web/src/test/fixtures/manifest.json` y se valida contra el esquema de esa
operación en el OpenAPI generado.

El validador es un subconjunto de JSON Schema escrito aquí a propósito: el
esquema que emite FastAPI usa `$ref`, `allOf`, `anyOf`, `type`, `properties`,
`required`, `items` y `enum`, y nada más. Traer una dependencia nueva para eso
costaría más de lo que resuelve.

Uso::

    python scripts/check_contract_fixtures.py                    # exporta y valida
    python scripts/check_contract_fixtures.py --openapi ruta.json
    python scripts/check_contract_fixtures.py --min-coverage 80
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_FIXTURES = _REPO_ROOT / "web" / "src" / "test" / "fixtures"
_MANIFIESTO = _FIXTURES / "manifest.json"
_HOOKS = _REPO_ROOT / "web" / "src" / "hooks"

#: Rutas de la API citadas en `web/src/hooks`. El `${...}` de un template
#: literal se normaliza a `{}`, igual que se normaliza `{pursuit_id}` del
#: OpenAPI: lo que se compara es la operación, no el nombre del parámetro.
_RUTA_EN_HOOK = re.compile(r"/api/v1/[A-Za-z0-9/_.\-{}$()!]+")


def _normaliza_ruta(ruta: str) -> str:
    ruta = re.sub(r"\$\{[^}]*\}?", "{}", ruta)
    ruta = re.sub(r"\{[^}]*\}", "{}", ruta)
    ruta = ruta.split("?")[0].rstrip("/`\"'),;")
    return ruta or "/"


def operaciones_consumidas_por_hooks() -> set[str]:
    """Rutas normalizadas que `web/src/hooks` consume."""
    rutas: set[str] = set()
    for fichero in sorted(_HOOKS.glob("*.ts")) + sorted(_HOOKS.glob("*.tsx")):
        for bruto in _RUTA_EN_HOOK.findall(fichero.read_text(encoding="utf-8")):
            rutas.add(_normaliza_ruta(bruto))
    return rutas


def operaciones_del_openapi(doc: dict[str, Any]) -> set[str]:
    return {_normaliza_ruta(r) for r in (doc.get("paths") or {})}


# ── Validador de un subconjunto de JSON Schema ───────────────────────────────


def _resolver(
    esquema: dict[str, Any], doc: dict[str, Any], vistos: frozenset[str] = frozenset()
) -> dict[str, Any]:
    ref = esquema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/") or ref in vistos:
        return esquema
    nodo: Any = doc
    for parte in ref[2:].split("/"):
        if not isinstance(nodo, dict) or parte not in nodo:
            return esquema
        nodo = nodo[parte]
    if not isinstance(nodo, dict):
        return esquema
    return _resolver(nodo, doc, vistos | {ref})


_TIPOS: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
}


def validar(
    valor: Any,
    esquema: dict[str, Any],
    doc: dict[str, Any],
    *,
    ruta: str = "$",
    profundidad: int = 0,
) -> list[str]:
    """Devuelve la lista de incumplimientos de *valor* frente a *esquema*."""
    if profundidad > 12:
        return []
    esquema = _resolver(esquema, doc)
    fallos: list[str] = []

    if "anyOf" in esquema or "oneOf" in esquema:
        ramas = esquema.get("anyOf") or esquema.get("oneOf") or []
        for rama in ramas:
            if isinstance(rama, dict) and not validar(
                valor, rama, doc, ruta=ruta, profundidad=profundidad + 1
            ):
                return []
        # Un `null` explícito contra una unión sin rama nula sí es un fallo,
        # pero si ninguna rama encaja no se puede señalar una en concreto.
        return [f"{ruta}: no encaja en ninguna rama de la unión"]

    for sub in esquema.get("allOf", []) or []:
        if isinstance(sub, dict):
            fallos += validar(valor, sub, doc, ruta=ruta, profundidad=profundidad + 1)

    tipo = esquema.get("type")
    if isinstance(tipo, str) and tipo in _TIPOS:
        # `bool` es subclase de `int` en Python; un booleano no es un entero.
        if tipo in ("integer", "number") and isinstance(valor, bool):
            return [*fallos, f"{ruta}: se esperaba {tipo} y llega boolean"]
        if not isinstance(valor, _TIPOS[tipo]):
            recibido = "null" if valor is None else type(valor).__name__
            return [*fallos, f"{ruta}: se esperaba {tipo} y llega {recibido}"]
    elif tipo == "null" and valor is not None:
        return [*fallos, f"{ruta}: se esperaba null"]

    enum = esquema.get("enum")
    if isinstance(enum, list) and valor not in enum:
        return [*fallos, f"{ruta}: {valor!r} no está en {enum}"]

    if isinstance(valor, dict):
        propiedades = esquema.get("properties")
        if isinstance(propiedades, dict):
            for requerido in esquema.get("required", []) or []:
                if requerido not in valor:
                    fallos.append(f"{ruta}.{requerido}: falta un campo requerido")
            for clave, sub in valor.items():
                sub_esquema = propiedades.get(clave)
                if sub_esquema is None:
                    if esquema.get("additionalProperties") is False or (
                        propiedades and esquema.get("additionalProperties") is None
                    ):
                        fallos.append(f"{ruta}.{clave}: el contrato no declara este campo")
                    continue
                if isinstance(sub_esquema, dict):
                    fallos += validar(
                        sub, sub_esquema, doc, ruta=f"{ruta}.{clave}", profundidad=profundidad + 1
                    )

    if isinstance(valor, list):
        items = esquema.get("items")
        if isinstance(items, dict):
            for i, elemento in enumerate(valor):
                fallos += validar(
                    elemento, items, doc, ruta=f"{ruta}[{i}]", profundidad=profundidad + 1
                )

    return fallos


# ── Manifiesto ───────────────────────────────────────────────────────────────


def _esquema_de(
    doc: dict[str, Any], metodo: str, ruta: str, clase: str, estado: str
) -> dict[str, Any] | None:
    operacion = (doc.get("paths") or {}).get(ruta, {}).get(metodo.lower())
    if not isinstance(operacion, dict):
        return None
    if clase == "request":
        contenido = (operacion.get("requestBody") or {}).get("content", {})
    else:
        contenido = (operacion.get("responses") or {}).get(estado, {}).get("content", {})
    json_ = contenido.get("application/json")
    if isinstance(json_, dict) and isinstance(json_.get("schema"), dict):
        return json_["schema"]
    return None


def _exportar_openapi() -> Path:
    from scripts.export_openapi import export_openapi

    destino = Path(tempfile.gettempdir()) / "tenderflow_openapi_contract.json"
    export_openapi(destino)
    return destino


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openapi", type=Path, help="OpenAPI ya exportado (si no, se exporta)")
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=80.0,
        help="Porcentaje mínimo de operaciones de hooks con fixture (default 80)",
    )
    args = parser.parse_args()

    if not _MANIFIESTO.exists():
        print(f"ERROR: falta {_MANIFIESTO.relative_to(_REPO_ROOT)}", file=sys.stderr)
        return 1

    ruta_openapi = args.openapi or _exportar_openapi()
    doc = json.loads(Path(ruta_openapi).read_text(encoding="utf-8"))
    manifiesto = json.loads(_MANIFIESTO.read_text(encoding="utf-8"))
    entradas = manifiesto.get("fixtures", [])

    errores: list[str] = []
    cubiertas: set[str] = set()

    for entrada in entradas:
        nombre = entrada.get("fixture", "?")
        metodo = str(entrada.get("method", "get")).lower()
        ruta = entrada.get("path", "")
        clase = entrada.get("kind", "response")
        estado = str(entrada.get("status", "200"))

        fichero = _FIXTURES / nombre
        if not fichero.exists():
            errores.append(f"{nombre}: el manifiesto lo declara y el fichero no existe")
            continue

        esquema = _esquema_de(doc, metodo, ruta, clase, estado)
        if esquema is None:
            errores.append(
                f"{nombre}: {metodo.upper()} {ruta} ({clase} {estado}) no existe en el OpenAPI"
            )
            continue

        try:
            valor = json.loads(fichero.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errores.append(f"{nombre}: JSON inválido ({exc})")
            continue

        fallos = validar(valor, esquema, doc)
        for f in fallos:
            errores.append(f"{nombre} [{metodo.upper()} {ruta}] {f}")
        if not fallos:
            cubiertas.add(_normaliza_ruta(ruta))

    consumidas = operaciones_consumidas_por_hooks() & operaciones_del_openapi(doc)
    cobertura = 100.0 * len(cubiertas & consumidas) / len(consumidas) if consumidas else 100.0

    for e in errores:
        print(f"ERROR {e}", file=sys.stderr)

    sin_fixture = sorted(consumidas - cubiertas)
    if sin_fixture:
        print(f"\nOperaciones de hooks sin fixture validada ({len(sin_fixture)}):")
        for r in sin_fixture:
            print(f"  · {r}")

    print(
        f"\nCobertura: {len(cubiertas & consumidas)}/{len(consumidas)} operaciones "
        f"({cobertura:.0f} %); mínimo exigido {args.min_coverage:.0f} %."
    )

    if errores:
        print(f"{len(errores)} fixture/s no cuadran con el contrato.", file=sys.stderr)
        return 1
    if cobertura < args.min_coverage:
        print(
            f"ERROR: cobertura {cobertura:.0f} % por debajo del mínimo {args.min_coverage:.0f} %.",
            file=sys.stderr,
        )
        return 1
    print("OK: los fixtures del frontend cuadran con el contrato de la API.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
