"""Detecta cambios incompatibles del contrato OpenAPI (C8.2).

`codegen-drift` verifica que `api/openapi.json` y `web/src/generated/api.d.ts`
están **sincronizados**. Eso no es lo mismo que decir si el contrato cambió de
forma incompatible: borrar un campo de una respuesta pasa ese gate en verde,
porque los dos artefactos se regeneran juntos y el diff cuadra.

Este script compara el OpenAPI de la base con el de la PR y falla si encuentra
un cambio que rompería a un consumidor ya desplegado. La lista de qué cuenta
como incompatible está en `docs/api-design.md`.

Uso::

    python scripts/check_api_breaking.py --base base.json --head head.json
    python scripts/check_api_breaking.py --base b.json --head h.json \\
        --allow-breaking --rfc docs/rfc/NNN-retirada.md

Sin `--allow-breaking`, un cambio incompatible devuelve 1. Con él, se exige
además `--rfc`: romper el contrato es legítimo, hacerlo sin dejar dicho dónde
está documentado no.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_METODOS = ("get", "put", "post", "delete", "patch", "head", "options")

#: Palabras clave que estrechan el dominio de un parámetro o de un campo.
#: Subirlas (`minimum`, `minLength`) o bajarlas (`maximum`, `maxLength`) rompe a
#: quien ya envía un valor que antes valía.
_COTAS_SUPERIORES = ("maximum", "exclusiveMaximum", "maxLength", "maxItems")
_COTAS_INFERIORES = ("minimum", "exclusiveMinimum", "minLength", "minItems")


class Hallazgo:
    __slots__ = ("donde", "que")

    def __init__(self, donde: str, que: str) -> None:
        self.donde = donde
        self.que = que

    def __str__(self) -> str:
        return f"{self.donde}: {self.que}"


def _resolver(esquema: dict[str, Any], doc: dict[str, Any], _vistos: set[str] | None = None) -> dict[str, Any]:
    """Sigue `$ref` dentro del mismo documento. Corta los ciclos."""
    vistos = _vistos or set()
    ref = esquema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/") or ref in vistos:
        return esquema
    vistos.add(ref)
    nodo: Any = doc
    for parte in ref[2:].split("/"):
        if not isinstance(nodo, dict) or parte not in nodo:
            return esquema
        nodo = nodo[parte]
    if not isinstance(nodo, dict):
        return esquema
    return _resolver(nodo, doc, vistos)


#: Profundidad máxima al aplanar un esquema de respuesta.
#:
#: Seis niveles cubren de sobra el contrato real (`Paginated[T] → items[] → T →
#: sub-objeto`); más allá el coste crece y el valor no. La protección de ciclos
#: la da `_vistos` sobre las `$ref` ya expandidas, no este número.
_PROFUNDIDAD_MAXIMA = 6


def _campos_planos(
    esquema: dict[str, Any],
    doc: dict[str, Any],
    *,
    prefijo: str = "",
    profundidad: int = 0,
    vistos: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Aplana un esquema a `{ruta.del.campo: tipo}`.

    Descender importa: la respuesta de `GET /licitaciones` es
    `PaginatedResponse[LicitacionSummary]`, así que un campo que desaparece lo
    hace **dentro** de `items[]`. Comparar solo el nivel superior encontraría
    `total`, `limit`, `offset` e `items`, y ninguno de los campos que un cliente
    consume de verdad.

    Las uniones (`anyOf`/`oneOf`) no se aplanan: un campo que solo existe en una
    de las ramas no está garantizado, y tratarlo como campo del contrato daría
    falsos positivos al reordenarse la unión.
    """
    if profundidad > _PROFUNDIDAD_MAXIMA:
        return {}

    ref = esquema.get("$ref")
    if isinstance(ref, str):
        if ref in vistos:
            return {}
        vistos = vistos | {ref}
    esquema = _resolver(esquema, doc)

    campos: dict[str, str] = {}

    items = esquema.get("items")
    if isinstance(items, dict):
        campos.update(
            _campos_planos(
                items,
                doc,
                prefijo=f"{prefijo}[]",
                profundidad=profundidad + 1,
                vistos=vistos,
            )
        )

    for sub in esquema.get("allOf", []) or []:
        if isinstance(sub, dict):
            campos.update(
                _campos_planos(
                    sub, doc, prefijo=prefijo, profundidad=profundidad + 1, vistos=vistos
                )
            )

    propiedades = esquema.get("properties")
    if isinstance(propiedades, dict):
        for nombre, sub in propiedades.items():
            if not isinstance(sub, dict):
                continue
            ruta = f"{prefijo}.{nombre}" if prefijo else nombre
            resuelto = _resolver(sub, doc)
            campos[ruta] = _tipo(resuelto)
            campos.update(
                _campos_planos(
                    sub, doc, prefijo=ruta, profundidad=profundidad + 1, vistos=vistos
                )
            )
    return campos


def _tipo(esquema: dict[str, Any]) -> str:
    tipo = esquema.get("type")
    if isinstance(tipo, str):
        return tipo
    if "anyOf" in esquema or "oneOf" in esquema:
        return "union"
    return "desconocido"


def _esquema_de_respuesta(operacion: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any] | None:
    for codigo in ("200", "201"):
        contenido = operacion.get("responses", {}).get(codigo, {}).get("content", {})
        json_ = contenido.get("application/json")
        if isinstance(json_, dict) and isinstance(json_.get("schema"), dict):
            return _resolver(json_["schema"], doc)
    return None


def _esquema_de_peticion(operacion: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any] | None:
    contenido = operacion.get("requestBody", {}).get("content", {})
    json_ = contenido.get("application/json")
    if isinstance(json_, dict) and isinstance(json_.get("schema"), dict):
        return _resolver(json_["schema"], doc)
    return None


def _requeridos(esquema: dict[str, Any] | None, doc: dict[str, Any]) -> set[str]:
    if not esquema:
        return set()
    esquema = _resolver(esquema, doc)
    req = set(esquema.get("required", []) or [])
    for sub in esquema.get("allOf", []) or []:
        if isinstance(sub, dict):
            req |= _requeridos(sub, doc)
    return req


def _params(operacion: dict[str, Any], doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    salida: dict[str, dict[str, Any]] = {}
    for p in operacion.get("parameters", []) or []:
        if not isinstance(p, dict):
            continue
        p = _resolver(p, doc)
        nombre = p.get("name")
        if isinstance(nombre, str):
            salida[nombre] = p
    return salida


def _cotas(esquema: dict[str, Any]) -> dict[str, Any]:
    """Cotas de un parámetro, mirando también dentro de su `schema`."""
    fuente = esquema.get("schema") if isinstance(esquema.get("schema"), dict) else esquema
    return {k: v for k, v in fuente.items() if k in (*_COTAS_SUPERIORES, *_COTAS_INFERIORES, "enum")}


def comparar(base: dict[str, Any], head: dict[str, Any]) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []
    paths_base = base.get("paths", {}) or {}
    paths_head = head.get("paths", {}) or {}

    for ruta, ops_base in paths_base.items():
        if ruta not in paths_head:
            hallazgos.append(Hallazgo(ruta, "la ruta desaparece"))
            continue
        ops_head = paths_head[ruta]

        for metodo, op_base in ops_base.items():
            if metodo not in _METODOS or not isinstance(op_base, dict):
                continue
            op_head = ops_head.get(metodo)
            if not isinstance(op_head, dict):
                hallazgos.append(Hallazgo(f"{metodo.upper()} {ruta}", "el método desaparece"))
                continue
            donde = f"{metodo.upper()} {ruta}"

            # 1. Códigos de estado documentados que desaparecen.
            for codigo in op_base.get("responses", {}):
                if codigo not in op_head.get("responses", {}):
                    hallazgos.append(Hallazgo(donde, f"deja de documentar el estado {codigo}"))

            # 2. Campos de respuesta que desaparecen o cambian de tipo.
            resp_base = _esquema_de_respuesta(op_base, base)
            resp_head = _esquema_de_respuesta(op_head, head)
            if resp_base is not None and resp_head is not None:
                campos_base = _campos_planos(resp_base, base)
                campos_head = _campos_planos(resp_head, head)
                for campo, t_base in campos_base.items():
                    if campo not in campos_head:
                        hallazgos.append(
                            Hallazgo(donde, f"la respuesta pierde el campo `{campo}`")
                        )
                        continue
                    t_head = campos_head[campo]
                    if t_base != t_head and "desconocido" not in (t_base, t_head):
                        hallazgos.append(
                            Hallazgo(
                                donde,
                                f"el campo `{campo}` de la respuesta pasa de "
                                f"`{t_base}` a `{t_head}`",
                            )
                        )
            elif resp_base is not None and resp_head is None:
                hallazgos.append(Hallazgo(donde, "la respuesta deja de declarar esquema JSON"))

            # 3. Campos de petición que pasan a ser requeridos, o nacen requeridos.
            req_base = _requeridos(_esquema_de_peticion(op_base, base), base)
            peticion_head = _esquema_de_peticion(op_head, head)
            req_head = _requeridos(peticion_head, head)
            for campo in sorted(req_head - req_base):
                hallazgos.append(
                    Hallazgo(donde, f"el campo `{campo}` de la petición pasa a ser requerido")
                )

            # 4. Parámetros que desaparecen, pasan a requeridos o se estrechan.
            params_base = _params(op_base, base)
            params_head = _params(op_head, head)
            for nombre, p_base in params_base.items():
                p_head = params_head.get(nombre)
                if p_head is None:
                    hallazgos.append(Hallazgo(donde, f"desaparece el parámetro `{nombre}`"))
                    continue
                if p_head.get("required") and not p_base.get("required"):
                    hallazgos.append(
                        Hallazgo(donde, f"el parámetro `{nombre}` pasa a ser requerido")
                    )
                cotas_base, cotas_head = _cotas(p_base), _cotas(p_head)
                for clave in _COTAS_SUPERIORES:
                    if clave in cotas_base and clave in cotas_head:
                        if _menor(cotas_head[clave], cotas_base[clave]):
                            hallazgos.append(
                                Hallazgo(
                                    donde,
                                    f"el parámetro `{nombre}` estrecha `{clave}`: "
                                    f"{cotas_base[clave]} → {cotas_head[clave]}",
                                )
                            )
                for clave in _COTAS_INFERIORES:
                    if clave in cotas_base and clave in cotas_head:
                        if _menor(cotas_base[clave], cotas_head[clave]):
                            hallazgos.append(
                                Hallazgo(
                                    donde,
                                    f"el parámetro `{nombre}` estrecha `{clave}`: "
                                    f"{cotas_base[clave]} → {cotas_head[clave]}",
                                )
                            )
                enum_base = cotas_base.get("enum")
                enum_head = cotas_head.get("enum")
                if isinstance(enum_base, list) and isinstance(enum_head, list):
                    perdidos = [v for v in enum_base if v not in enum_head]
                    if perdidos:
                        hallazgos.append(
                            Hallazgo(
                                donde,
                                f"el parámetro `{nombre}` deja de aceptar {perdidos}",
                            )
                        )
            for nombre, p_head in params_head.items():
                if nombre not in params_base and p_head.get("required"):
                    hallazgos.append(
                        Hallazgo(donde, f"nace el parámetro requerido `{nombre}`")
                    )

    return hallazgos


def _menor(a: Any, b: Any) -> bool:
    try:
        return float(a) < float(b)
    except (TypeError, ValueError):
        return False


def _resumen_aditivo(base: dict[str, Any], head: dict[str, Any]) -> list[str]:
    """Lo que se añadió. No rompe nada, pero conviene verlo en el job."""
    paths_base = base.get("paths", {}) or {}
    paths_head = head.get("paths", {}) or {}
    nuevas = sorted(set(paths_head) - set(paths_base))
    return [f"ruta nueva: {r}" for r in nuevas]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="OpenAPI de la rama base")
    parser.add_argument("--head", type=Path, required=True, help="OpenAPI de la PR")
    parser.add_argument(
        "--allow-breaking",
        action="store_true",
        help="La PR lleva la etiqueta `api-breaking`. Exige --rfc.",
    )
    parser.add_argument("--rfc", help="RFC que documenta la retirada")
    args = parser.parse_args()

    base = json.loads(args.base.read_text(encoding="utf-8"))
    head = json.loads(args.head.read_text(encoding="utf-8"))

    for linea in _resumen_aditivo(base, head):
        print(f"  + {linea}")

    hallazgos = comparar(base, head)
    if not hallazgos:
        print("OK: el contrato no cambia de forma incompatible.")
        return 0

    print(f"\n{len(hallazgos)} cambio/s incompatible/s del contrato:\n", file=sys.stderr)
    for h in hallazgos:
        print(f"  - {h}", file=sys.stderr)

    if not args.allow_breaking:
        print(
            "\nSi el cambio es deliberado: etiquetá la PR con `api-breaking`, escribí la "
            "RFC de retirada y enlazala. La política está en docs/api-design.md.",
            file=sys.stderr,
        )
        return 1
    if not args.rfc:
        print(
            "\nLa etiqueta `api-breaking` está, pero falta `--rfc`: romper el contrato es "
            "legítimo, hacerlo sin dejar dicho dónde está documentado no.",
            file=sys.stderr,
        )
        return 1

    print(f"\nCambio incompatible aceptado, documentado en {args.rfc}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
