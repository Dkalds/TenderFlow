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

Lo que se enseña al etiquetar es lo que ve quien lee el anuncio —título,
descripción, CPV, órgano, importe—, y **no** ``keyword_match`` ni la
probabilidad del modelo: el golden va a juzgar a esas dos fuentes, y verlas
antes de decidir ancla la respuesta (misma regla que el runbook
``docs/runbooks/etiquetado-ti.md``). Cada etiqueta queda con ``source`` y
``fecha`` para poder auditar un lote sospechoso. «Dudoso» marca la fila con
``dudoso: true`` y la saca de la cola; ``--dudosos`` la vuelve a enseñar.

Uso
---
Muestrear (necesita BD, o un export con ``--desde``) y luego etiquetar::

    python -m scripts.sample_golden_candidates --n 400 --out data/candidatos.jsonl
    python -m scripts.revisar_golden_candidates data/candidatos.jsonl

Ver si el golden set ya sostiene lo que se le pide (no necesita BD; si hay un
modelo en ``data/models/`` mide además la estabilidad del umbral por
bootstrap, con la misma rejilla que ``services.ml_eval.tune_threshold_on_golden``)::

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
import datetime as dt
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

_RAIZ = Path(__file__).resolve().parent.parent
_GOLDEN_POR_DEFECTO = _RAIZ / "tests" / "fixtures" / "golden_set.jsonl"

#: Positivos sin keyword que necesita el holdout. No sale de `ml_eval` porque
#: allí no está expresado como constante; su justificación está en el backlog.
_MIN_POSITIVOS_SIN_KEYWORD = 30

#: Ancho p5-p95 del umbral por debajo del cual se lo considera estable.
#: Orientativo, no un criterio del gate: es ~1/6 del rango útil del barrido
#: (0,30-0,95). Con los 27 ejemplos semilla el ancho medido era 0,26.
_ANCHO_UMBRAL_ORIENTATIVO = 0.10

#: Procedencia que se graba en cada etiqueta puesta con esta herramienta.
_SOURCE = "revisar_golden_candidates"


class _Predictor(Protocol):
    def predict(
        self, text: str, *, cpv: str | None = ..., importe: float | None = ...
    ) -> tuple[bool, float]: ...


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
    """Enseña lo que ve quien lee el anuncio. Ni ``keyword_match`` ni la nota
    del muestreo (estrato, ``ml_proba``): anclarían la respuesta."""
    importe = fila.get("importe")
    importe_txt = f"{importe:,.0f} €".replace(",", ".") if isinstance(importe, int | float) else "—"
    print("\n" + "─" * 78)
    print(f"[{indice}/{total}]  {fila.get('id') or ''}")
    print(f"CPV {fila.get('cpv') or '—'}   {importe_txt}")
    print(f"Órgano: {_resumen(str(fila.get('organo') or '—'), 120)}")
    print("─" * 78)
    print(_resumen(str(fila.get("titulo") or ""), 400))
    descripcion = _resumen(str(fila.get("descripcion") or ""))
    if descripcion:
        print(f"\n{descripcion}")


def _pendiente(fila: dict[str, Any], *, revisitar_dudosos: bool) -> bool:
    """Sin etiqueta y, salvo que se pidan, no marcada como dudosa.

    Un dudoso que vuelve en cada sesión obliga a saltarlo una y otra vez, y
    al final se etiqueta por cansancio: la peor etiqueta posible.
    """
    if fila.get("label") is not None:
        return False
    return revisitar_dudosos or not fila.get("dudoso")


def _etiquetar(fila: dict[str, Any], label: int, hoy: str) -> None:
    fila["label"] = label
    fila["source"] = _SOURCE
    fila["fecha"] = hoy
    fila.pop("dudoso", None)
    fila["note"] = str(fila.get("note") or "").replace("PENDIENTE DE ETIQUETAR", "").strip(" ·")


def revisar(
    ruta: Path,
    *,
    leer: Callable[[str], str] = input,
    hoy: str | None = None,
    revisitar_dudosos: bool = False,
) -> int:
    """Bucle de etiquetado. Devuelve cuántas etiquetas nuevas se escribieron.

    ``leer`` y ``hoy`` existen para el test: el bucle es el mismo con teclado
    que con una lista de respuestas.
    """
    cabecera, filas = _leer_jsonl(ruta)
    if not filas:
        print(f"No hay candidatos en {ruta}", file=sys.stderr)
        return 0
    fecha = hoy or dt.date.today().isoformat()

    pendientes = [
        i for i, f in enumerate(filas) if _pendiente(f, revisitar_dudosos=revisitar_dudosos)
    ]
    if not pendientes:
        dudosos = sum(1 for f in filas if f.get("label") is None and f.get("dudoso"))
        extra = f" ({dudosos} dudosos: --dudosos para revisarlos)" if dudosos else ""
        print(f"No quedan candidatos pendientes en {ruta}{extra}.")
        return 0

    print(f"{len(pendientes)} candidatos pendientes de {len(filas)}.")
    print(_AYUDA)

    escritas = 0
    for orden, indice in enumerate(pendientes, start=1):
        fila = filas[indice]
        _pintar(fila, orden, len(pendientes))
        while True:
            try:
                respuesta = leer("  [1/0/s/d/?/q] > ").strip().lower()
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
                fila["dudoso"] = True
                fila["fecha"] = fecha
                _escribir_jsonl(ruta, cabecera, filas)
                break
            if respuesta in {"0", "1"}:
                _etiquetar(fila, int(respuesta), fecha)
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


def _beta_de_produccion() -> float:
    """β con la que ``SAPClassifier`` afina el umbral: sqrt(coste FN / coste FP)."""
    from config import settings

    coste_fp = float(getattr(settings, "ML_COST_FP", 1.0))
    coste_fn = float(getattr(settings, "ML_COST_FN", 1.0))
    return float((coste_fn / coste_fp) ** 0.5)


def informe_umbral(
    filas_tune: list[dict[str, Any]], clf: _Predictor, *, beta: float
) -> dict[str, float | int] | None:
    """Bootstrap del umbral sobre la mitad ``tune``, la única donde se elige.

    Reutiliza :func:`services.ml_eval.umbral_bootstrap`, que elige con la misma
    rejilla que el tuning que llega a producción. ``None`` si la mitad no tiene
    las dos clases.
    """
    from services.ml_eval import umbral_bootstrap

    y = [int(f["label"]) for f in filas_tune]
    probas = [
        float(
            clf.predict(
                f"{f.get('titulo') or ''} {f.get('descripcion') or ''}".strip(),
                cpv=str(f["cpv"]) if f.get("cpv") is not None else None,
                importe=float(f["importe"]) if f.get("importe") is not None else None,
            )[1]
        )
        for f in filas_tune
    ]
    resultado = umbral_bootstrap(y, probas, beta=beta)
    return resultado.as_dict() if resultado is not None else None


def cargar_modelo_local() -> _Predictor | None:
    """El clasificador SAP de ``data/models/``, o ``None`` si no hay (sin red)."""
    try:
        from services.ml.sap_classifier import SAPClassifier

        if not SAPClassifier.is_available():
            return None
        return SAPClassifier.load()
    except Exception as exc:  # el informe de conteos no debe morir por el modelo
        print(f"[aviso] no se pudo cargar el modelo ({exc}); se omite el bootstrap del umbral")
        return None


def _imprimir_umbral(filas_tune: list[dict[str, Any]], clf: _Predictor | None) -> None:
    if clf is None:
        print("  umbral (bootstrap)  sin modelo local: no se mide (data/models/ vacío)")
        return
    informe = informe_umbral(filas_tune, clf, beta=_beta_de_produccion())
    if informe is None:
        print("  umbral (bootstrap)  la mitad tune no tiene las dos clases: no hay umbral")
        return
    ancho = float(informe["ancho_p5_p95"])
    veredicto = (
        "estable" if ancho <= _ANCHO_UMBRAL_ORIENTATIVO else "inestable: depende de la muestra"
    )
    print(
        f"  umbral (bootstrap)  {informe['umbral']:.2f}  sigma={informe['sigma']:.3f}  "
        f"p5-p95=[{informe['p5']:.2f}, {informe['p95']:.2f}]  ancho={ancho:.2f}  "
        f"({veredicto}; orientativo <= {_ANCHO_UMBRAL_ORIENTATIVO:.2f})"
    )


def estado(ruta_golden: Path, *, clf: _Predictor | None = None) -> bool:
    """Informa de si el golden set cumple ya sus mínimos. Devuelve si cumple.

    Con ``clf`` mide además la estabilidad del umbral (informativa: no entra
    en el veredicto, que es el de ``services.ml_eval`` y el backlog).
    """
    from services.ml_eval import MIN_HOLDOUT_EXAMPLES, MIN_TUNE_EXAMPLES

    _, filas = _leer_jsonl(ruta_golden)
    etiquetadas = [f for f in filas if f.get("label") is not None]

    conteo = {"tune": 0, "holdout": 0}
    positivos_sin_kw = {"tune": 0, "holdout": 0}
    filas_tune: list[dict[str, Any]] = []
    for fila in etiquetadas:
        mitad = str(fila.get("split") or "") or _split_de(str(fila.get("id") or ""))
        mitad = mitad if mitad in conteo else "holdout"
        conteo[mitad] += 1
        if mitad == "tune":
            filas_tune.append(fila)
        if int(fila["label"]) == 1 and fila.get("keyword_match") is False:
            positivos_sin_kw[mitad] += 1
    n_positivos = sum(1 for f in etiquetadas if int(f["label"]) == 1)

    print(f"\nGolden set: {ruta_golden}")
    print(f"  etiquetados         {len(etiquetadas)} de {len(filas)} líneas")
    print(f"  positivos           {n_positivos}   negativos {len(etiquetadas) - n_positivos}")
    print(f"  tune                {conteo['tune']:4d}  (mínimo {MIN_TUNE_EXAMPLES})")
    print(f"  holdout             {conteo['holdout']:4d}  (mínimo {MIN_HOLDOUT_EXAMPLES})")
    print(
        f"  positivos sin kw    tune={positivos_sin_kw['tune']:3d} "
        f"holdout={positivos_sin_kw['holdout']:3d}  (mínimo {_MIN_POSITIVOS_SIN_KEYWORD} en holdout)"
    )
    _imprimir_umbral(filas_tune, clf)

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
    parser.add_argument(
        "--dudosos", action="store_true", help="volver a enseñar los marcados como dudosos"
    )
    parser.add_argument(
        "--sin-modelo",
        action="store_true",
        help="no cargar el modelo local (omite el bootstrap del umbral)",
    )
    args = parser.parse_args(argv)

    def _clf() -> _Predictor | None:
        return None if args.sin_modelo else cargar_modelo_local()

    if args.estado:
        return 0 if estado(args.golden, clf=_clf()) else 1

    if args.candidatos is None:
        parser.error("hace falta el JSONL de candidatos (o --estado)")

    if args.anexar:
        anexar(args.candidatos, args.golden)
        estado(args.golden, clf=_clf())
        return 0

    revisar(args.candidatos, revisitar_dudosos=args.dudosos)
    # Tras una sesión de etiquetado, solo conteos: cargar el modelo para el
    # bootstrap haría esperar a quien solo quiere parar. Para eso, --estado.
    estado(args.golden)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
