"""Revisa a teclado los casos del golden de la ficha del pliego.

Por qué existe
--------------
``scripts/capturar_ficha_golden.py`` deja en cada caso la ficha vigente como
propuesta, con todos los hechos sin veredicto. Decidir si cada uno es cierto es
trabajo de una persona —**un golden que rellena una máquina solo mide el
acuerdo con esa máquina**— y este script quita lo que rodea a esa decisión: un
hecho cada vez, con su cita y su página, una tecla por veredicto, y guardado
después de cada respuesta para poder parar y retomar.

Mismo patrón que ``scripts/revisar_golden_candidates.py``.

Uso
---
Revisar lo que extrajo la app (y lo que un eval posterior dejó pendiente)::

    python scripts/revisar_ficha_golden.py <caso>

En los casos completos, después de leer el pliego entero, añadir lo que la
ficha omitió. La cita tiene que estar literalmente en la página::

    python scripts/revisar_ficha_golden.py <caso> --anadir

Ver si el conjunto ya sirve para medir (no necesita nada más que los ficheros)::

    python scripts/revisar_ficha_golden.py --estado

Criterio de aceptación (``docs/plans/2026-10-eval-ficha-pliego.md`` §11)
------------------------------------------------------------------------
Diez casos, tres de ellos completos, y ningún hecho sin veredicto.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

_RAIZ_REPO = Path(__file__).resolve().parent.parent
if str(_RAIZ_REPO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_REPO))

from services.rag.fact_sheet import _validated_evidence  # noqa: E402
from services.rag.ficha_golden import (  # noqa: E402
    CAMPOS_CLAVE,
    FAMILIAS,
    NOMBRE_GOLDEN,
    Caso,
    CasoGolden,
    HechoGolden,
    escribir_golden,
    escribir_pendientes,
    leer_caso,
    leer_pendientes,
    listar_casos,
    modelo_de,
    sin_revisar,
)
from shared.tender_facts import EvidenceRef  # noqa: E402

RAIZ_POR_DEFECTO = _RAIZ_REPO / "tests" / "eval" / "fixtures" / "fichas"

MIN_CASOS = 10
MIN_COMPLETOS = 3

Lector = Callable[[str], str]

#: Campos que la revisión nunca pregunta: los pone el script.
_CAMPOS_FIJOS = frozenset({"description", "confidence", "evidence"})

_AYUDA = """
  c = correcto                      i = incorrecto (falso, o no es de esta familia)
  v = el sitio es ese, el valor no  s = saltar (lo dejo sin decidir)
  ? = ver la página entera          q = guardar y salir
"""


class _Salir(Exception):
    """El usuario pidió salir (``q``) o cerró la entrada."""


def _guardar(carpeta: Path, golden: CasoGolden) -> None:
    # Se revalida antes de escribir: los hechos se tocan en sitio, y un golden
    # que no encaja en su esquema tiene que fallar aquí y no al evaluarlo.
    escribir_golden(carpeta, CasoGolden.model_validate(golden.model_dump()))


def _pagina(caso: Caso, documento_id: object, page_number: object) -> dict[str, Any] | None:
    for pagina in caso.paginas:
        if pagina.get("documento_id") == documento_id and pagina.get("page_number") == page_number:
            return pagina
    return None


def _pintar(familia: str, hecho: dict[str, Any], orden: int, total: int) -> None:
    print("\n" + "─" * 78)
    print(f"[{orden}/{total}]  {familia}")
    print("─" * 78)
    for campo, valor in hecho.items():
        if campo in _CAMPOS_FIJOS or valor is None:
            continue
        marca = " *" if campo in CAMPOS_CLAVE[familia] else ""
        print(f"  {campo}{marca}: {valor}")
    print(f"  {hecho.get('description') or ''}")
    for cita in hecho.get("evidence") or []:
        print(f"\n  doc {cita.get('documento_id')} · pág. {cita.get('page_number')}")
        print(f"  «{cita.get('quote')}»")


def _ver_paginas(caso: Caso, hecho: dict[str, Any]) -> None:
    for cita in hecho.get("evidence") or []:
        pagina = _pagina(caso, cita.get("documento_id"), cita.get("page_number"))
        print(f"\n── doc {cita.get('documento_id')} · pág. {cita.get('page_number')} ──")
        print(str(pagina.get("texto")) if pagina else "(esa página no está entre las capturadas)")


def _pedir_campo(familia: str, hecho: dict[str, Any], campo: str, leer: Lector) -> Any:
    """Pide un campo hasta que encaje en el modelo. Vacío conserva el valor; ``-`` lo borra."""
    modelo = modelo_de(familia)
    while True:
        respuesta = leer(f"    {campo} [{hecho.get(campo)}] > ").strip()
        if not respuesta:
            return hecho.get(campo)
        valor = None if respuesta == "-" else respuesta
        try:
            validado = modelo.model_validate({**hecho, campo: valor})
        except ValidationError as exc:
            motivo = next((e["msg"] for e in exc.errors() if campo in e["loc"]), str(exc))
            print(f"    No vale: {motivo}")
            continue
        return validado.model_dump(mode="json")[campo]


def _corregir(familia: str, hecho: dict[str, Any], leer: Lector) -> HechoGolden | None:
    """Pregunta los campos clave. ``None`` si no cambió ninguno."""
    print("    Escribe el valor bueno; vacío lo deja como está, «-» lo deja sin valor.")
    nuevo = dict(hecho)
    for campo in CAMPOS_CLAVE[familia]:
        nuevo[campo] = _pedir_campo(familia, nuevo, campo, leer)
    modelo = modelo_de(familia)
    antes = modelo.model_validate(hecho).model_dump(mode="json")
    despues = modelo.model_validate(nuevo).model_dump(mode="json")
    cambiados = [c for c in CAMPOS_CLAVE[familia] if antes[c] != despues[c]]
    if not cambiados:
        return None
    return HechoGolden(
        veredicto="corregido",
        hecho=despues,
        valor_extraido={campo: hecho.get(campo) for campo in cambiados},
    )


def _decidir(
    caso: Caso, familia: str, hecho: dict[str, Any], orden: int, total: int, leer: Lector
) -> HechoGolden | None:
    """Pide el veredicto de un hecho. ``None`` si se salta."""
    _pintar(familia, hecho, orden, total)
    con_clave = bool(CAMPOS_CLAVE[familia])
    teclas = "c/i/v/s/?/q" if con_clave else "c/i/s/?/q"
    while True:
        respuesta = leer(f"  [{teclas}] > ").strip().lower()
        if respuesta == "q":
            raise _Salir
        if respuesta == "?":
            _ver_paginas(caso, hecho)
        elif respuesta == "s":
            return None
        elif respuesta == "c":
            return HechoGolden(veredicto="correcto", hecho=hecho)
        elif respuesta == "i":
            return HechoGolden(veredicto="incorrecto", hecho=hecho)
        elif respuesta == "v" and con_clave:
            corregido = _corregir(familia, hecho, leer)
            if corregido is not None:
                return corregido
            print("  No cambiaste ningún valor: si el hecho está bien, es «c».")
        elif respuesta == "v":
            print("  Esta familia no tiene un valor que corregir: es «c» o «i».")
        else:
            print("  No te he entendido." + _AYUDA)


def revisar(carpeta: Path, *, leer: Lector = input) -> int:
    """Bucle de revisión de un caso. Devuelve cuántos veredictos se escribieron."""
    caso = leer_caso(carpeta)
    golden = caso.golden
    pendientes = leer_pendientes(carpeta)
    por_revisar = [
        (familia, indice)
        for familia, items in golden.hechos.items()
        for indice, item in enumerate(items)
        if item.veredicto is None
    ]
    total = len(pendientes) + len(por_revisar)
    if not total:
        print(f"El caso {caso.nombre} no tiene nada por revisar.")
        return 0

    print(f"{total} hechos por revisar en {caso.nombre}.")
    print(_AYUDA)
    escritos = 0
    orden = 0
    try:
        # Primero lo que dejó pendiente un eval: son hechos que el extractor
        # actual saca y nadie ha juzgado, y solo entran al golden con veredicto.
        for familia, hecho in list(pendientes):
            orden += 1
            decidido = _decidir(caso, familia, hecho, orden, total, leer)
            if decidido is None:
                continue
            golden.hechos.setdefault(familia, []).append(decidido)
            pendientes.remove((familia, hecho))
            _guardar(carpeta, golden)
            escribir_pendientes(carpeta, pendientes)
            escritos += 1
        for familia, indice in por_revisar:
            orden += 1
            decidido = _decidir(
                caso, familia, golden.hechos[familia][indice].hecho, orden, total, leer
            )
            if decidido is None:
                continue
            golden.hechos[familia][indice] = decidido
            _guardar(carpeta, golden)
            escritos += 1
    except (_Salir, EOFError, KeyboardInterrupt):
        print(f"\nGuardado: {escritos} veredictos nuevos en {caso.nombre}. Vuelve cuando quieras.")
        return escritos

    print(f"\nHecho: {escritos} veredictos nuevos en {caso.nombre}.")
    if golden.completo:
        print("Es un caso completo: tras leer el pliego, añade lo omitido con --anadir.")
    return escritos


def _pedir_cita(caso: Caso, leer: Lector) -> EvidenceRef | None:
    """Documento, página y cita literal. ``None`` si se deja la cita vacía."""
    documentos = sorted({(p.get("documento_id"), p.get("filename")) for p in caso.paginas}, key=str)
    for documento_id, filename in documentos:
        print(f"    doc {documento_id}: {filename or '(sin nombre)'}")
    indice = {(int(p["documento_id"]), int(p["page_number"])): p for p in caso.paginas}
    while True:
        try:
            documento_id = int(leer("    documento_id > ").strip())
            page_number = int(leer("    page_number > ").strip())
        except ValueError:
            print("    Hacen falta dos números.")
            continue
        break
    while True:
        cita = leer("    cita literal (vacío cancela) > ").strip()
        if not cita:
            return None
        try:
            propuesta = EvidenceRef(documento_id=documento_id, page_number=page_number, quote=cita)
        except ValidationError as exc:
            print(f"    No vale: {exc.errors()[0]['msg']}")
            continue
        validada = _validated_evidence(propuesta, indice)
        if validada is not None:
            return validada
        print(
            "    Esa cita no está literalmente en esa página ni en otra del mismo "
            "documento. Cópiala del pliego tal cual."
        )


def anadir(carpeta: Path, *, leer: Lector = input) -> int:
    """Añade a un caso completo lo que la ficha omitió. Devuelve cuántos hechos."""
    caso = leer_caso(carpeta)
    golden = caso.golden
    if not golden.completo:
        print(
            f"El caso {caso.nombre} no es completo: solo se añade lo omitido en los que se "
            "leen enteros (captúralo con --completo).",
            file=sys.stderr,
        )
        return 0

    print("Familias: " + ", ".join(FAMILIAS))
    anadidos = 0
    try:
        while True:
            familia = leer("\n  familia (vacío termina) > ").strip()
            if not familia:
                break
            if familia not in FAMILIAS:
                print("  Esa familia no existe.")
                continue
            cita = _pedir_cita(caso, leer)
            if cita is None:
                continue
            modelo = modelo_de(familia)
            hecho: dict[str, Any] = {
                "description": cita.quote,
                "confidence": 1.0,
                "evidence": [cita.model_dump(mode="json")],
            }
            obligatorios = [
                nombre
                for nombre, campo in modelo.model_fields.items()
                if campo.is_required() and nombre not in _CAMPOS_FIJOS
            ]
            preguntar = [*CAMPOS_CLAVE[familia]]
            preguntar += [c for c in obligatorios if c not in preguntar]
            for campo in preguntar:
                respuesta = leer(f"    {campo} > ").strip()
                if respuesta:
                    hecho[campo] = respuesta
            descripcion = leer("    descripción (vacío = la cita) > ").strip()
            if descripcion:
                hecho["description"] = descripcion
            try:
                validado = modelo.model_validate(hecho)
            except ValidationError as exc:
                print("  No se ha añadido:")
                for error in exc.errors():
                    print(f"    {'.'.join(str(p) for p in error['loc'])}: {error['msg']}")
                continue
            golden.hechos.setdefault(familia, []).append(
                HechoGolden(veredicto="añadido", hecho=validado.model_dump(mode="json"))
            )
            _guardar(carpeta, golden)
            anadidos += 1
            print("  Añadido.")
    except (EOFError, KeyboardInterrupt):
        pass
    print(f"\nGuardado: {anadidos} hechos añadidos en {caso.nombre}.")
    return anadidos


def estado(raiz: Path) -> bool:
    """Informa de si el conjunto ya sirve para medir. Devuelve si cumple."""
    casos = [leer_caso(carpeta) for carpeta in listar_casos(raiz)]
    completos = sum(1 for caso in casos if caso.golden.completo)
    pendientes_de_veredicto = 0

    print(f"\nCasos en {raiz}")
    for carpeta, caso in zip(listar_casos(raiz), casos, strict=True):
        faltan = sin_revisar(caso.golden) + len(leer_pendientes(carpeta))
        pendientes_de_veredicto += faltan
        hechos = sum(len(items) for items in caso.golden.hechos.values())
        print(
            f"  {caso.nombre:32} {'completo' if caso.golden.completo else 'parcial':9}"
            f" {hechos:4d} hechos  {faltan:4d} sin veredicto"
        )

    faltas: list[str] = []
    if len(casos) < MIN_CASOS:
        faltas.append(f"faltan {MIN_CASOS - len(casos)} casos (hay {len(casos)} de {MIN_CASOS})")
    if completos < MIN_COMPLETOS:
        faltas.append(f"faltan {MIN_COMPLETOS - completos} casos completos (hay {completos})")
    if pendientes_de_veredicto:
        faltas.append(f"quedan {pendientes_de_veredicto} hechos sin veredicto")

    if faltas:
        print("\n  NO cumple todavía:")
        for falta in faltas:
            print(f"    · {falta}")
        return False
    print(f"\n  Cumple: {len(casos)} casos, {completos} completos, todo revisado.")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Revisa a teclado los casos del golden de la ficha del pliego."
    )
    parser.add_argument("caso", nargs="?", help="nombre de la carpeta del caso")
    parser.add_argument(
        "--anadir", action="store_true", help="añadir lo que la ficha omitió (casos completos)"
    )
    parser.add_argument("--estado", action="store_true", help="solo informar de si ya basta")
    parser.add_argument("--raiz", type=Path, default=RAIZ_POR_DEFECTO)
    args = parser.parse_args(argv)

    if args.estado:
        return 0 if estado(args.raiz) else 1
    if not args.caso:
        parser.error("indica el caso a revisar, o --estado")

    carpeta = args.raiz / args.caso
    if not (carpeta / NOMBRE_GOLDEN).is_file():
        print(f"No existe el caso {carpeta}. Captúralo antes.", file=sys.stderr)
        return 2
    if args.anadir:
        # `anadir` explica por qué se niega en un caso parcial; aquí solo se
        # traduce a código de salida.
        completo = leer_caso(carpeta).golden.completo
        anadir(carpeta)
        return 0 if completo else 1
    revisar(carpeta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
