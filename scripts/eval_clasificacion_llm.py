"""Eval manual del prompt de clasificación («¿es TI?») contra el LLM real.

Un cambio en ``services/llm_tech_labeling.py`` (la pregunta, el modelo) no lo
verifica ningún test: todos sustituyen al proveedor. Hasta ahora se comprobaba
a mano, con un script distinto en cada sesión. Este fija la medida.

Qué mide, y por qué esas tres cosas:

* **Estabilidad.** Cada anuncio se clasifica varias veces. Un anuncio cuyas
  respuestas no coinciden en ``es_ti`` es «inestable». En el cambio v3 → v4
  (2026-10-11) la primera redacción movió un anuncio dudoso a «es TI» en 6 de
  33 respuestas, frente a 0 de 34 con el prompt anterior: mirar una sola
  respuesta por anuncio no lo habría enseñado.
* **Confianza en las inestables.** El modelo declara 0,9 en respuestas que se
  contradicen entre sí; si esa media baja, el prompt consigue que la confianza
  refleje la duda.
* **Acierto**, solo si la entrada trae la respuesta esperada: mayoría de las
  repeticiones contra ``es_ti`` del golden.

Con ``--contra`` compara con el resultado guardado de otra ejecución (la del
prompt anterior, lanzada desde master o antes de editar): qué anuncios cambian
de mayoría. Es la comparación A/B, y no necesita etiquetas.

**No usa base de datos ni Redis**: el proceso arranca con ``DATABASE_URL`` y
``REDIS_URL`` vacías, así que el presupuesto LLM cuenta en memoria y nada se
escribe fuera de la máquina aunque el ``.env`` apunte a producción. Sí llama al
proveedor real: necesita su API key y consume cuota. Por eso vive fuera de CI.

Entrada: por defecto ``tests/fixtures/golden_ti.jsonl``. Mientras ese golden
siga vacío hay que pasar ``--entrada``: un JSONL (o un JSON con una lista) de
filas con ``id_externo``, ``titulo``, ``descripcion``, ``cpv`` y, si se conoce,
``es_ti``.

Uso::

    make eval-clasificacion ARGS="--entrada filas.jsonl --salida antes.json"
    # ... se edita el prompt ...
    make eval-clasificacion ARGS="--entrada filas.jsonl --contra antes.json"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Clasifica una fila de ``licitaciones``; devuelve algo con ``es_ti``,
#: ``confianza_es_ti`` y ``scores`` (``services.llm_tech_labeling.Clasificacion``).
Clasificador = Callable[[dict[str, Any]], Any]


def cargar_filas(ruta: Path) -> list[dict[str, Any]]:
    """Lee un JSONL (tolera comentarios ``#`` y líneas vacías) o un JSON con una lista."""
    texto = ruta.read_text(encoding="utf-8")
    if texto.lstrip().startswith("["):
        return [dict(fila) for fila in json.loads(texto)]
    filas = []
    for cruda in texto.splitlines():
        linea = cruda.strip()
        if linea and not linea.startswith("#"):
            filas.append(json.loads(linea))
    return filas


def filas_del_golden() -> list[dict[str, Any]]:
    """El golden real de «¿es TI?», con la forma de una fila de ``licitaciones``."""
    from services.ml.golden_ti import cargar_golden_ti

    return [
        {
            "id_externo": e.id_externo,
            "titulo": e.titulo,
            "descripcion": e.descripcion,
            "cpv": e.cpv,
            "es_ti": e.es_ti,
        }
        for e in cargar_golden_ti()
    ]


def evaluar(
    filas: list[dict[str, Any]], clasificar: Clasificador, repeticiones: int
) -> list[dict[str, Any]]:
    """Clasifica cada fila ``repeticiones`` veces. Un fallo del LLM se anota, no corta."""
    resultados = []
    for i, fila in enumerate(filas, start=1):
        respuestas: list[dict[str, Any]] = []
        for _ in range(repeticiones):
            try:
                clasificacion = clasificar(fila)
            except Exception as exc:  # el eval sigue: un 429 no invalida al resto
                respuestas.append({"error": f"{type(exc).__name__}: {exc}"[:200]})
                continue
            respuestas.append(
                {
                    "es_ti": clasificacion.es_ti,
                    "confianza": clasificacion.confianza_es_ti,
                    "tecnologias": sorted(clasificacion.scores),
                }
            )
        resultado = {
            "id_externo": str(fila.get("id_externo") or f"fila-{i}"),
            "esperado": fila.get("es_ti"),
            "respuestas": respuestas,
        }
        resultados.append(resultado)
        vistas = " ".join(_abreviar(r) for r in respuestas)
        print(f"[{i}/{len(filas)}] {resultado['id_externo']}: {vistas}", flush=True)
    return resultados


def _abreviar(respuesta: dict[str, Any]) -> str:
    if "error" in respuesta:
        return "error"
    es_ti = {True: "sí", False: "no", None: "?"}[respuesta["es_ti"]]
    confianza = respuesta["confianza"]
    return es_ti if confianza is None else f"{es_ti}({confianza:.2f})"


def _validas(resultado: dict[str, Any]) -> list[dict[str, Any]]:
    """Las respuestas en las que el modelo contestó ``es_ti`` (ni error ni ``None``)."""
    return [r for r in resultado["respuestas"] if r.get("es_ti") is not None]


def mayoria(resultado: dict[str, Any]) -> bool | None:
    """``es_ti`` más repetido entre las respuestas válidas; ``None`` si no hay o empatan."""
    validas = _validas(resultado)
    positivas = sum(1 for r in validas if r["es_ti"])
    negativas = len(validas) - positivas
    if positivas == negativas:
        return None
    return positivas > negativas


def es_inestable(resultado: dict[str, Any]) -> bool:
    return len({r["es_ti"] for r in _validas(resultado)}) > 1


def resumir(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    """Los recuentos del informe. Función pura: es lo que cubren los tests."""
    respuestas = [r for res in resultados for r in res["respuestas"]]
    inestables = [res for res in resultados if es_inestable(res)]
    confianzas = [
        r["confianza"] for res in inestables for r in _validas(res) if r["confianza"] is not None
    ]
    etiquetadas = [res for res in resultados if res["esperado"] is not None]
    return {
        "filas": len(resultados),
        "respuestas": len(respuestas),
        "errores": sum(1 for r in respuestas if "error" in r),
        "sin_es_ti": sum(1 for r in respuestas if "error" not in r and r["es_ti"] is None),
        "inestables": [res["id_externo"] for res in inestables],
        "confianza_media_inestables": (
            round(sum(confianzas) / len(confianzas), 3) if confianzas else None
        ),
        "etiquetadas": len(etiquetadas),
        "aciertos": sum(1 for res in etiquetadas if mayoria(res) == res["esperado"]),
    }


def comparar(antes: list[dict[str, Any]], despues: list[dict[str, Any]]) -> dict[str, Any]:
    """Qué cambia entre dos ejecuciones sobre los mismos anuncios."""
    previos = {res["id_externo"]: res for res in antes}
    comunes = [res for res in despues if res["id_externo"] in previos]
    cambios = []
    for res in comunes:
        era, es = mayoria(previos[res["id_externo"]]), mayoria(res)
        if era != es:
            cambios.append({"id_externo": res["id_externo"], "antes": era, "despues": es})
    return {
        "comunes": len(comunes),
        "cambios_de_mayoria": cambios,
        "inestables_antes": sum(1 for res in comunes if es_inestable(previos[res["id_externo"]])),
        "inestables_despues": sum(1 for res in comunes if es_inestable(res)),
    }


def _texto(valor: bool | None) -> str:
    return {True: "es TI", False: "no es TI", None: "sin mayoría"}[valor]


def _imprimir_resumen(resumen: dict[str, Any]) -> None:
    print(f"\n{'=' * 70}")
    print(
        f"{resumen['filas']} anuncios, {resumen['respuestas']} respuestas: "
        f"{resumen['errores']} con error, {resumen['sin_es_ti']} sin `es_ti`."
    )
    inestables = resumen["inestables"]
    print(f"Inestables (las repeticiones no coinciden en `es_ti`): {len(inestables)}")
    for id_externo in inestables:
        print(f"  {id_externo}")
    if resumen["confianza_media_inestables"] is not None:
        print(
            f"Confianza media declarada en las inestables: "
            f"{resumen['confianza_media_inestables']:.2f} (si no refleja la duda, ronda 0,9)."
        )
    if resumen["etiquetadas"]:
        print(
            f"Acierto por mayoría: {resumen['aciertos']}/{resumen['etiquetadas']} "
            f"= {resumen['aciertos'] / resumen['etiquetadas']:.0%}."
        )
    else:
        print("Acierto: sin población — la entrada no trae `es_ti` esperado.")


def _imprimir_comparacion(comparacion: dict[str, Any]) -> None:
    cambios = comparacion["cambios_de_mayoria"]
    print(
        f"\nContra la ejecución anterior ({comparacion['comunes']} anuncios en común): "
        f"{len(cambios)} cambian de mayoría; inestables "
        f"{comparacion['inestables_antes']} → {comparacion['inestables_despues']}."
    )
    for cambio in cambios:
        print(f"  {cambio['id_externo']}: {_texto(cambio['antes'])} → {_texto(cambio['despues'])}")


def _sin_bd_ni_redis() -> None:
    """Deja el proceso sin almacenes externos antes de importar nada del proyecto.

    En pydantic-settings el entorno gana al ``.env``: vaciar las dos variables
    aquí basta para que ``settings`` no cargue las de un checkout que apunta a
    producción. Se reasignan también los atributos por si ``config`` ya estaba
    importado (los tests).
    """
    os.environ["DATABASE_URL"] = ""
    os.environ["REDIS_URL"] = ""

    from pydantic import SecretStr

    from config import settings

    settings.DATABASE_URL = SecretStr("")
    settings.REDIS_URL = ""


def main(argv: list[str] | None = None, clasificar: Clasificador | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Eval manual del prompt de clasificación contra el LLM real."
    )
    parser.add_argument("--entrada", type=Path, default=None, help="JSONL/JSON de filas")
    parser.add_argument("--repeticiones", type=int, default=3, help="Llamadas por anuncio (3)")
    parser.add_argument("--limit", type=int, default=30, help="Máximo de anuncios (30)")
    parser.add_argument("--model", default=None, help="Modelo (LLM_TECH_LABELING_MODEL)")
    parser.add_argument("--salida", type=Path, default=None, help="Guarda el resultado en JSON")
    parser.add_argument("--contra", type=Path, default=None, help="Resultado anterior a comparar")
    parser.add_argument(
        "--min-acierto",
        type=float,
        default=None,
        help="Acierto mínimo por mayoría (0-1). Sin este flag solo se informa.",
    )
    args = parser.parse_args(argv)

    # La consola de Windows (cp1252) no tiene «→»: sin esto el informe revienta.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    _sin_bd_ni_redis()

    from config import settings
    from services import llm_tech_labeling

    filas = cargar_filas(args.entrada) if args.entrada else filas_del_golden()
    filas = filas[: args.limit]
    if not filas:
        print(
            "Sin anuncios que evaluar: el golden de «¿es TI?» está vacío. "
            "Pasá --entrada con un JSONL de filas (id_externo, titulo, descripcion, cpv)."
        )
        return 2

    model = args.model or settings.LLM_TECH_LABELING_MODEL
    if clasificar is None:

        def clasificar(fila: dict[str, Any]) -> Any:
            return llm_tech_labeling.classify_licitacion(fila, model=model)

    print(
        f"Prompt {llm_tech_labeling.PROMPT_VERSION}, modelo {model}: "
        f"{len(filas)} anuncios, {args.repeticiones} repeticiones cada uno."
    )
    resultados = evaluar(filas, clasificar, args.repeticiones)
    resumen = resumir(resultados)
    if resumen["errores"] == resumen["respuestas"]:
        # Sin esto el informe diría «acierto 0 %» de un modelo al que no se llegó.
        print(
            "Ninguna llamada devolvió respuesta: no se evaluó nada. Lo habitual es que "
            "falte la API key del proveedor en el entorno."
        )
        return 2
    _imprimir_resumen(resumen)

    if args.contra:
        anterior = json.loads(args.contra.read_text(encoding="utf-8"))
        _imprimir_comparacion(comparar(anterior["resultados"], resultados))

    if args.salida:
        args.salida.write_text(
            json.dumps(
                {
                    "prompt_version": llm_tech_labeling.PROMPT_VERSION,
                    "modelo": model,
                    "repeticiones": args.repeticiones,
                    "resultados": resultados,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"Resultado guardado en {args.salida}.")

    if args.min_acierto is not None and resumen["etiquetadas"]:
        tasa = resumen["aciertos"] / resumen["etiquetadas"]
        if tasa < args.min_acierto:
            print(f"FALLO: acierto {tasa:.0%} por debajo del mínimo ({args.min_acierto:.0%}).")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
