"""Etiqueta a mano los candidatos del golden set, y mide si ya es suficiente.

Por qué existe
--------------
``scripts/sample_golden_candidates.py`` resuelve bien la mitad difícil —*qué*
conviene mandar a etiquetar— y termina escribiendo un JSONL con ``label: null``.
Ahí es donde el trabajo lleva meses parado, y el motivo es prosaico: la otra
mitad consiste en abrir 400 líneas de JSON en un editor y rellenar un campo en
cada una sin equivocarse de línea. Nadie hace eso dos veces.

Este script no etiqueta —**no puede**, y fabricar las etiquetas sería peor que
no tenerlas: el golden set es el único sitio del repo con juicio humano
independiente del filtro de keywords, y si lo rellena una máquina, medir el
modelo contra él sólo mide el acuerdo con esa máquina—. Lo que hace es quitar
toda la fricción que rodea a la decisión humana:

- presenta un candidato cada vez, con lo que hace falta para decidir;
- captura la respuesta con una tecla y **guarda después de cada una**, así que
  se puede parar y retomar sin perder nada;
- al terminar, dice si el conjunto ya cumple lo que ``services.ml_eval`` exige,
  que es la pregunta que de verdad importa y que hoy nadie puede responder sin
  hacer cuentas a mano.

Uso
---
Muestrear (necesita BD) y luego etiquetar::

    python -m scripts.sample_golden_candidates --n 400 --out data/candidatos.jsonl
    python -m scripts.revisar_golden_candidates data/candidatos.jsonl

Ver si el golden set ya sostiene lo que se le pide (no necesita BD)::

    python -m scripts.revisar_golden_candidates --estado

Anexar lo etiquetado al golden set::

    python -m scripts.revisar_golden_candidates data/candidatos.jsonl --anexar

Criterio de aceptación (de ``services.ml_eval`` y del backlog)
--------------------------------------------------------------
- >= 60 ejemplos en cada mitad (``MIN_TUNE_EXAMPLES``/``MIN_HOLDOUT_EXAMPLES``).
- >= 30 positivos humanos **sin keyword** en el holdout, para que
  ``recall_no_keyword`` tenga resolución útil: es la métrica que decide si el
  modelo aporta algo sobre ``matches_sap()``, y con 6 se mueve a saltos de 16,7
  puntos.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_RAIZ = Path(__file__).resolve().parent.parent
_GOLDEN_POR_DEFECTO = _RAIZ / "tests" / "fixtures" / "golden_set.jsonl"

#: Positivos sin keyword que necesita el holdout. No sale de `ml_eval` porque
#: allí no está expresado como constante; su justificación está en el backlog.
_MIN_POSITIVOS_SIN_KEYWORD = 30

_AYUDA = """
  1 = es una oportunidad SAP        0 = no lo es
  s = saltar (lo dejo sin decidir)  d = dudoso (lo marco y sigo)
  ? = ver la descripción entera     q = guardar y salir
"""


def _leer_jsonl(ruta: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Devuelve (cabecera de comentarios, filas). Conserva los ``#`` del fichero."""
    if not ruta.exists():
        return [], []
    cabecera: list[str] = []
    filas: list[dict[str, Any]] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        limpia = linea.strip()
        if not limpia:
            continue
        if limpia.startswith("#"):
            # Sólo se conservan los comentarios de cabecera; uno intercalado
            # perdería su sitio al reescribir y confundiría más que ayudar.
            if not filas:
                cabecera.append(linea)
            continue
        filas.append(json.loads(limpia))
    return cabecera, filas


def _escribir_jsonl(ruta: Path, cabecera: list[str], filas: list[dict[str, Any]]) -> None:
    """Reescribe el fichero entero. Atómico: primero a un temporal, luego rename.

    Se guarda después de **cada** etiqueta, así que un corte de luz o un Ctrl-C
    no pueden dejar el fichero a medias — que es justo lo que haría que alguien
    no se fiara de la herramienta y volviera al editor.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for linea in cabecera:
            fh.write(linea + "\n")
        for fila in filas:
            fh.write(json.dumps(fila, ensure_ascii=False) + "\n")
    tmp.replace(ruta)


def _resumen(texto: str, ancho: int = 300) -> str:
    texto = " ".join((texto or "").split())
    return texto if len(texto) <= ancho else texto[:ancho] + "…"


def _pintar(fila: dict[str, Any], indice: int, total: int) -> None:
    importe = fila.get("importe")
    importe_txt = f"{importe:,.0f} €".replace(",", ".") if isinstance(importe, int | float) else "—"
    print("\n" + "─" * 78)
    print(f"[{indice}/{total}]  CPV {fila.get('cpv') or '—'}   {importe_txt}")
    print(f"keyword_match={fila.get('keyword_match')}   {fila.get('note') or ''}")
    print("─" * 78)
    print(_resumen(str(fila.get("titulo") or ""), 400))
    descripcion = _resumen(str(fila.get("descripcion") or ""))
    if descripcion:
        print(f"\n{descripcion}")


def revisar(ruta: Path) -> int:
    """Bucle de etiquetado. Devuelve cuántas etiquetas nuevas se escribieron."""
    cabecera, filas = _leer_jsonl(ruta)
    if not filas:
        print(f"No hay candidatos en {ruta}", file=sys.stderr)
        return 0

    pendientes = [i for i, f in enumerate(filas) if f.get("label") is None]
    if not pendientes:
        print(f"Todos los candidatos de {ruta} ya están etiquetados.")
        return 0

    print(f"{len(pendientes)} candidatos sin etiquetar de {len(filas)}.")
    print(_AYUDA)

    escritas = 0
    for orden, indice in enumerate(pendientes, start=1):
        fila = filas[indice]
        _pintar(fila, orden, len(pendientes))
        while True:
            try:
                respuesta = input("  [1/0/s/d/?/q] > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nGuardado. Vuelve cuando quieras.")
                return escritas
            if respuesta == "?":
                print(str(fila.get("descripcion") or "(sin descripción)"))
                continue
            if respuesta == "q":
                print(f"\nGuardado: {escritas} etiquetas nuevas en {ruta}")
                return escritas
            if respuesta == "s":
                break
            if respuesta == "d":
                fila["note"] = (str(fila.get("note") or "") + " · DUDOSO").strip(" ·")
                _escribir_jsonl(ruta, cabecera, filas)
                break
            if respuesta in {"0", "1"}:
                fila["label"] = int(respuesta)
                fila["note"] = (
                    str(fila.get("note") or "").replace("PENDIENTE DE ETIQUETAR", "").strip(" ·")
                )
                _escribir_jsonl(ruta, cabecera, filas)
                escritas += 1
                break
            print("  No te he entendido." + _AYUDA)

    print(f"\nHecho: {escritas} etiquetas nuevas en {ruta}")
    return escritas


def _split_de(id_ejemplo: str) -> str:
    """Mitad a la que cae un ejemplo, con la misma regla que ``services.ml_eval``.

    Se importa la función real en vez de replicar el hash: si la regla cambiara,
    dos implementaciones darían recuentos distintos y este informe diría que el
    conjunto vale cuando no vale.
    """
    from services.ml_eval import SPLIT_TUNE, GoldenExample, asignar_splits

    ejemplo = GoldenExample(id=id_ejemplo, titulo="", descripcion="", label=0)
    asignado = asignar_splits([ejemplo])[0]
    return SPLIT_TUNE if asignado.split == SPLIT_TUNE else "holdout"


def estado(ruta_golden: Path) -> bool:
    """Informa de si el golden set cumple ya sus mínimos. Devuelve si cumple."""
    from services.ml_eval import MIN_HOLDOUT_EXAMPLES, MIN_TUNE_EXAMPLES

    _, filas = _leer_jsonl(ruta_golden)
    etiquetadas = [f for f in filas if f.get("label") is not None]

    conteo = {"tune": 0, "holdout": 0}
    positivos_sin_kw = {"tune": 0, "holdout": 0}
    for fila in etiquetadas:
        mitad = str(fila.get("split") or "") or _split_de(str(fila.get("id") or ""))
        mitad = mitad if mitad in conteo else "holdout"
        conteo[mitad] += 1
        if int(fila["label"]) == 1 and fila.get("keyword_match") is False:
            positivos_sin_kw[mitad] += 1

    print(f"\nGolden set: {ruta_golden}")
    print(f"  etiquetados         {len(etiquetadas)} de {len(filas)} líneas")
    print(f"  tune                {conteo['tune']:4d}  (mínimo {MIN_TUNE_EXAMPLES})")
    print(f"  holdout             {conteo['holdout']:4d}  (mínimo {MIN_HOLDOUT_EXAMPLES})")
    print(
        f"  positivos sin kw    tune={positivos_sin_kw['tune']:3d} "
        f"holdout={positivos_sin_kw['holdout']:3d}  (mínimo {_MIN_POSITIVOS_SIN_KEYWORD} en holdout)"
    )

    faltas: list[str] = []
    if conteo["tune"] < MIN_TUNE_EXAMPLES:
        faltas.append(f"faltan {MIN_TUNE_EXAMPLES - conteo['tune']} ejemplos en tune")
    if conteo["holdout"] < MIN_HOLDOUT_EXAMPLES:
        faltas.append(f"faltan {MIN_HOLDOUT_EXAMPLES - conteo['holdout']} ejemplos en holdout")
    if positivos_sin_kw["holdout"] < _MIN_POSITIVOS_SIN_KEYWORD:
        faltan = _MIN_POSITIVOS_SIN_KEYWORD - positivos_sin_kw["holdout"]
        faltas.append(f"faltan {faltan} positivos sin keyword en holdout")

    if faltas:
        print("\n  NO cumple todavía:")
        for falta in faltas:
            print(f"    · {falta}")
        print(
            "\n  Mientras no cumpla, el umbral servido y `recall_no_keyword` se "
            "apoyan en poca evidencia\n  y el gate de promoción bloquea o deja pasar "
            "casi por azar."
        )
        return False

    print("\n  Cumple los mínimos de services.ml_eval.")
    return True


def anexar(ruta_candidatos: Path, ruta_golden: Path) -> int:
    """Añade al golden set las filas ya etiquetadas. Devuelve cuántas añadió.

    Se niega a anexar filas sin etiquetar y a duplicar ids que ya estén: el
    golden set es un fichero que se edita a mano cada pocos meses, y un
    duplicado silencioso ahí sesga la métrica sin que nada falle.
    """
    _, candidatos = _leer_jsonl(ruta_candidatos)
    cabecera_golden, golden = _leer_jsonl(ruta_golden)

    existentes = {str(f.get("id")) for f in golden}
    nuevas = [
        f for f in candidatos if f.get("label") is not None and str(f.get("id")) not in existentes
    ]
    sin_etiquetar = sum(1 for f in candidatos if f.get("label") is None)

    if not nuevas:
        print("Nada que anexar: no hay filas etiquetadas nuevas.")
        return 0

    for fila in nuevas:
        fila.pop("split", None)  # lo asigna `asignar_splits` por hash del id
    _escribir_jsonl(ruta_golden, cabecera_golden, golden + nuevas)

    print(f"Anexadas {len(nuevas)} filas a {ruta_golden}")
    if sin_etiquetar:
        print(f"Quedan {sin_etiquetar} candidatos sin etiquetar en {ruta_candidatos}")
    return len(nuevas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidatos", nargs="?", type=Path, help="JSONL de candidatos")
    parser.add_argument(
        "--estado", action="store_true", help="sólo informar de si el golden set ya basta"
    )
    parser.add_argument("--anexar", action="store_true", help="anexar lo etiquetado al golden set")
    parser.add_argument("--golden", type=Path, default=_GOLDEN_POR_DEFECTO)
    args = parser.parse_args(argv)

    if args.estado:
        return 0 if estado(args.golden) else 1

    if args.candidatos is None:
        parser.error("hace falta el JSONL de candidatos (o --estado)")

    if args.anexar:
        anexar(args.candidatos, args.golden)
        estado(args.golden)
        return 0

    revisar(args.candidatos)
    estado(args.golden)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
