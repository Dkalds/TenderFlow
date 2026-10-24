"""Evaluación del modelo de nivel 1, «¿es TI?» (plan de tres niveles, F3, §4).

Qué decide este módulo, y nada más:

- **PR-AUC** (precisión media, la misma definición que
  ``sklearn.metrics.average_precision_score``) con intervalo por bootstrap,
  y la **diferencia pareada** entre dos puntuadores sobre los mismos
  remuestreos: dos intervalos que se solapan no dicen si uno gana al otro;
  el intervalo de la diferencia, sí.
- Los dos **baselines** del gate: «solo keywords» (la puerta de reglas) y
  «solo CPV 48/72». Un puntuador binario (0/1) tiene PR-AUC igual que
  cualquier otro: lo que cuenta es contra qué se le compara.
- Los dos **umbrales** que parten la probabilidad en tres bandas: TI
  (precisión ≥ :data:`PRECISION_MIN_TI`), no TI (se pierde como mucho
  :data:`PERDIDA_RECALL_MAX` de los positivos) y dudoso, que va al LLM y
  después a la cola humana.
- El **gate de promoción**: el candidato elegido bate a los dos baselines en
  el holdout (la cota inferior del IC95 de la diferencia es > 0), y se mide
  aparte dentro de «CPV 48/72 sin keyword», que es la población donde el
  modelo puede aportar algo que las reglas no ven.
- La **elección** entre candidatos (A, B, A+B): gana el mejor PR-AUC, salvo
  que uno más simple no sea distinguible de él, y entonces gana el simple.

Puro: sin BD, sin sklearn, sin numpy. Los modelos y el golden los resuelve el
llamador (:mod:`services.ml.nivel1`, ``scripts/entrenar_nivel1.py``).

Lo que estas cifras **no** son: estimaciones de la población. El golden sale
de una muestra estratificada por raíz cuadrada del tamaño del estrato
(``scripts/muestra_etiquetado_ti.py``) más lo que llegue de la cola por
desacuerdo, así que sobrerrepresenta los estratos pequeños y los casos
difíciles. Sirven para comparar puntuadores sobre el mismo conjunto y para
fijar umbrales; la precisión real en producción la mide la semana en sombra.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, NamedTuple

#: Precisión mínima de la banda «TI» (spec §4, «Salida»).
PRECISION_MIN_TI = 0.95
#: Fracción máxima de positivos que puede caer en la banda «no TI» (spec §4).
PERDIDA_RECALL_MAX = 0.05
#: Holdout mínimo para que el gate decida: el mismo suelo que el golden legado
#: (``services.ml_eval.MIN_HOLDOUT_EXAMPLES``).
MIN_HOLDOUT = 60
#: Casos mínimos de cada clase dentro de «CPV 48/72 sin keyword» para medir ahí.
MIN_SUBPOBLACION_POR_CLASE = 10
#: Remuestreos del bootstrap y nivel del intervalo.
N_BOOTSTRAP = 1000
NIVEL_IC = 0.95
SEMILLA_BOOTSTRAP = 20260927

#: Candidatos de la spec, del más simple al más complejo: A (TF-IDF), B
#: (embeddings), A+B. El orden decide los empates.
ORDEN_SIMPLICIDAD: tuple[str, ...] = ("A", "B", "A+B")
BASELINE_KEYWORDS = "solo_keywords"
BASELINE_CPV = "solo_cpv_48_72"
BASELINES: tuple[str, ...] = (BASELINE_KEYWORDS, BASELINE_CPV)
SUBPOBLACION = "cpv_48_72_sin_keyword"

Banda = Literal["ti", "dudoso", "no_ti"]


class CasoEval(NamedTuple):
    """Lo que la evaluación necesita de un ejemplo del golden."""

    es_ti: bool
    tiene_keyword: bool
    cpv_ti: bool


# ── PR-AUC y bootstrap ──────────────────────────────────────────────────────


def average_precision(y: Sequence[bool], scores: Sequence[float]) -> float | None:
    """PR-AUC como ``sklearn.metrics.average_precision_score``: Σ (Rₖ - Rₖ₋₁)·Pₖ
    sobre los umbrales distintos, de mayor a menor. Los empates de score cuentan
    como un único umbral, así que un puntuador constante da la prevalencia.

    ``None`` si no hay ningún positivo: la métrica no está definida.
    """
    if len(y) != len(scores):
        raise ValueError(f"y ({len(y)}) y scores ({len(scores)}) no miden lo mismo")
    positivos = sum(1 for v in y if v)
    if positivos == 0:
        return None
    pares = sorted(zip(scores, y, strict=True), key=lambda par: -par[0])
    ap = 0.0
    tp = fp = 0
    recall_previo = 0.0
    i = 0
    while i < len(pares):
        umbral = pares[i][0]
        while i < len(pares) and pares[i][0] == umbral:
            if pares[i][1]:
                tp += 1
            else:
                fp += 1
            i += 1
        recall = tp / positivos
        ap += (recall - recall_previo) * (tp / (tp + fp))
        recall_previo = recall
    return ap


def _percentil(valores: Sequence[float], q: float) -> float:
    """Percentil con interpolación lineal (el ``linear`` de numpy)."""
    ordenados = sorted(valores)
    if not ordenados:
        raise ValueError("percentil de una lista vacía")
    posicion = q * (len(ordenados) - 1)
    bajo = int(posicion)
    alto = min(bajo + 1, len(ordenados) - 1)
    return ordenados[bajo] + (ordenados[alto] - ordenados[bajo]) * (posicion - bajo)


@dataclass(frozen=True)
class Intervalo:
    """Un estadístico con su IC por bootstrap. ``validos`` son los remuestreos
    en los que estaba definido (con algún positivo)."""

    valor: float
    bajo: float
    alto: float
    validos: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "valor": round(self.valor, 4),
            "ic_bajo": round(self.bajo, 4),
            "ic_alto": round(self.alto, 4),
            "remuestreos_validos": self.validos,
        }


def _bootstrap(
    n: int,
    estadistico: Callable[[list[int]], float | None],
    *,
    n_bootstrap: int,
    semilla: int,
) -> tuple[list[float], int]:
    rng = random.Random(semilla)  # noqa: S311  # nosec B311 — remuestreo reproducible, no criptografía
    valores: list[float] = []
    for _ in range(n_bootstrap):
        indices = [rng.randrange(n) for _ in range(n)]
        valor = estadistico(indices)
        if valor is not None:
            valores.append(valor)
    return valores, len(valores)


def _intervalo(valor: float, remuestreos: list[float], validos: int) -> Intervalo:
    alfa = (1.0 - NIVEL_IC) / 2
    if not remuestreos:
        return Intervalo(valor, valor, valor, 0)
    return Intervalo(
        valor, _percentil(remuestreos, alfa), _percentil(remuestreos, 1.0 - alfa), validos
    )


def ap_con_intervalo(
    y: Sequence[bool],
    scores: Sequence[float],
    *,
    n_bootstrap: int = N_BOOTSTRAP,
    semilla: int = SEMILLA_BOOTSTRAP,
) -> Intervalo | None:
    """PR-AUC con IC por bootstrap (percentiles). ``None`` sin positivos."""
    valor = average_precision(y, scores)
    if valor is None:
        return None

    def estadistico(indices: list[int]) -> float | None:
        return average_precision([y[i] for i in indices], [scores[i] for i in indices])

    remuestreos, validos = _bootstrap(len(y), estadistico, n_bootstrap=n_bootstrap, semilla=semilla)
    return _intervalo(valor, remuestreos, validos)


def diferencia_pareada(
    y: Sequence[bool],
    scores_a: Sequence[float],
    scores_b: Sequence[float],
    *,
    n_bootstrap: int = N_BOOTSTRAP,
    semilla: int = SEMILLA_BOOTSTRAP,
) -> Intervalo | None:
    """PR-AUC(a) - PR-AUC(b) con IC sobre los **mismos** remuestreos.

    Es la comparación que decide: los dos puntuadores ven los mismos ejemplos
    en cada remuestreo, así que la varianza que comparten (qué ejemplos
    tocaron) se cancela. ``None`` sin positivos.
    """
    ap_a = average_precision(y, scores_a)
    ap_b = average_precision(y, scores_b)
    if ap_a is None or ap_b is None:
        return None

    def estadistico(indices: list[int]) -> float | None:
        ys = [y[i] for i in indices]
        a = average_precision(ys, [scores_a[i] for i in indices])
        b = average_precision(ys, [scores_b[i] for i in indices])
        return None if a is None or b is None else a - b

    remuestreos, validos = _bootstrap(len(y), estadistico, n_bootstrap=n_bootstrap, semilla=semilla)
    return _intervalo(ap_a - ap_b, remuestreos, validos)


# ── Baselines ───────────────────────────────────────────────────────────────


def scores_baseline(casos: Sequence[CasoEval], baseline: str) -> list[float]:
    """Puntuación 0/1 de un baseline: la regla que el modelo tiene que batir."""
    if baseline == BASELINE_KEYWORDS:
        return [1.0 if c.tiene_keyword else 0.0 for c in casos]
    if baseline == BASELINE_CPV:
        return [1.0 if c.cpv_ti else 0.0 for c in casos]
    raise ValueError(f"baseline desconocido: {baseline!r}")


# ── Tres bandas ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Bandas:
    """Dos umbrales sobre P(es TI).

    - ``p >= umbral_ti`` → «ti». ``umbral_ti is None`` si ningún umbral llega a
      :data:`PRECISION_MIN_TI`: entonces no hay banda «ti» y todo lo que no es
      «no_ti» es dudoso.
    - ``p < umbral_no_ti`` → «no_ti».
    - El resto, «dudoso».

    Siempre ``umbral_no_ti <= umbral_ti``: si el modelo separa tan bien que
    los dos umbrales se cruzan, no hay banda dudosa.
    """

    umbral_no_ti: float
    umbral_ti: float | None

    def banda(self, p: float) -> Banda:
        if self.umbral_ti is not None and p >= self.umbral_ti:
            return "ti"
        if p < self.umbral_no_ti:
            return "no_ti"
        return "dudoso"

    def as_dict(self) -> dict[str, float | None]:
        return {
            "umbral_no_ti": round(self.umbral_no_ti, 6),
            "umbral_ti": None if self.umbral_ti is None else round(self.umbral_ti, 6),
        }


def elegir_bandas(
    y: Sequence[bool],
    scores: Sequence[float],
    *,
    precision_min: float = PRECISION_MIN_TI,
    perdida_recall_max: float = PERDIDA_RECALL_MAX,
) -> Bandas:
    """Los dos umbrales, elegidos sobre un conjunto (el ``tune`` del golden).

    - ``umbral_ti``: el **menor** umbral con precisión ≥ ``precision_min``
      entre lo que queda por encima. El menor, porque de los que cumplen es el
      que más positivos manda directamente a «TI».
    - ``umbral_no_ti``: el **mayor** umbral que deja por debajo como mucho
      ``perdida_recall_max`` de los positivos.

    Raises:
        ValueError: sin positivos no hay recall que perder y los umbrales no
            significan nada.
    """
    if len(y) != len(scores):
        raise ValueError(f"y ({len(y)}) y scores ({len(scores)}) no miden lo mismo")
    positivos = sum(1 for v in y if v)
    if positivos == 0:
        raise ValueError("sin positivos no se pueden elegir umbrales")

    pares = sorted(zip(scores, y, strict=True), key=lambda par: -par[0])
    umbral_ti: float | None = None
    umbral_no_ti = pares[-1][0]
    recall_min = 1.0 - perdida_recall_max
    no_ti_fijado = False
    tp = fp = 0
    i = 0
    while i < len(pares):
        umbral = pares[i][0]
        while i < len(pares) and pares[i][0] == umbral:
            if pares[i][1]:
                tp += 1
            else:
                fp += 1
            i += 1
        # Al bajar el umbral el recall solo crece: el primero que llega al
        # mínimo es el mayor umbral que lo cumple.
        if not no_ti_fijado and tp / positivos >= recall_min - 1e-12:
            umbral_no_ti = umbral
            no_ti_fijado = True
        if tp / (tp + fp) >= precision_min - 1e-12:
            umbral_ti = umbral
    if umbral_ti is not None and umbral_no_ti > umbral_ti:
        umbral_no_ti = umbral_ti
    return Bandas(umbral_no_ti=umbral_no_ti, umbral_ti=umbral_ti)


@dataclass(frozen=True)
class MetricasBandas:
    """Cómo se comportan unas bandas sobre un conjunto etiquetado."""

    n: int
    frac_ti: float
    frac_dudoso: float
    frac_no_ti: float
    #: Precisión dentro de la banda «ti»; ``None`` si la banda quedó vacía.
    precision_ti: float | None
    #: Fracción de positivos que cayó en «no_ti»; ``None`` sin positivos.
    recall_perdido_no_ti: float | None

    def as_dict(self) -> dict[str, float | int | None]:
        def r(v: float | None) -> float | None:
            return None if v is None else round(v, 4)

        return {
            "n": self.n,
            "frac_ti": r(self.frac_ti),
            "frac_dudoso": r(self.frac_dudoso),
            "frac_no_ti": r(self.frac_no_ti),
            "precision_ti": r(self.precision_ti),
            "recall_perdido_no_ti": r(self.recall_perdido_no_ti),
        }


def metricas_bandas(y: Sequence[bool], scores: Sequence[float], bandas: Bandas) -> MetricasBandas:
    n = len(y)
    if n == 0:
        return MetricasBandas(0, 0.0, 0.0, 0.0, None, None)
    asignadas = [bandas.banda(p) for p in scores]
    en_ti = [v for v, b in zip(y, asignadas, strict=True) if b == "ti"]
    positivos = sum(1 for v in y if v)
    perdidos = sum(1 for v, b in zip(y, asignadas, strict=True) if v and b == "no_ti")
    return MetricasBandas(
        n=n,
        frac_ti=asignadas.count("ti") / n,
        frac_dudoso=asignadas.count("dudoso") / n,
        frac_no_ti=asignadas.count("no_ti") / n,
        precision_ti=(sum(1 for v in en_ti if v) / len(en_ti)) if en_ti else None,
        recall_perdido_no_ti=(perdidos / positivos) if positivos else None,
    )


# ── Gate y elección ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InformeSubpoblacion:
    """El candidato dentro de «CPV 48/72 sin keyword». Ahí los dos baselines
    son constantes, así que batirlos es batir a la prevalencia."""

    n: int
    positivos: int
    ap: Intervalo | None
    #: PR-AUC(candidato) - prevalencia, pareada.
    sobre_prevalencia: Intervalo | None

    def as_dict(self) -> dict[str, object]:
        return {
            "n": self.n,
            "positivos": self.positivos,
            "ap": None if self.ap is None else self.ap.as_dict(),
            "sobre_prevalencia": (
                None if self.sobre_prevalencia is None else self.sobre_prevalencia.as_dict()
            ),
        }


@dataclass(frozen=True)
class InformeNivel1:
    """Resultado de :func:`evaluar_nivel1`. ``as_dict`` es lo que irá a
    ``model_versions.metrics_json`` cuando se registre (fase de sombra)."""

    n_holdout: int
    positivos_holdout: int
    ap: dict[str, Intervalo]
    sobre_baselines: dict[str, dict[str, Intervalo]]
    subpoblacion: dict[str, InformeSubpoblacion]
    bandas: dict[str, Bandas]
    bandas_holdout: dict[str, MetricasBandas]
    ganador: str | None
    eleccion: str
    apto: bool
    motivos: tuple[str, ...]
    sin_evaluar: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "n_holdout": self.n_holdout,
            "positivos_holdout": self.positivos_holdout,
            "pr_auc": {k: v.as_dict() for k, v in self.ap.items()},
            "sobre_baselines": {
                c: {b: iv.as_dict() for b, iv in d.items()} for c, d in self.sobre_baselines.items()
            },
            SUBPOBLACION: {c: s.as_dict() for c, s in self.subpoblacion.items()},
            "bandas": {c: b.as_dict() for c, b in self.bandas.items()},
            "bandas_holdout": {c: m.as_dict() for c, m in self.bandas_holdout.items()},
            "ganador": self.ganador,
            "eleccion": self.eleccion,
            "apto": self.apto,
            "motivos": list(self.motivos),
            "sin_evaluar": dict(self.sin_evaluar),
        }


def _fmt(iv: Intervalo) -> str:
    return f"{iv.valor:+.3f} [IC95 {iv.bajo:+.3f}, {iv.alto:+.3f}]"


def _elegir(
    y: Sequence[bool],
    scores: Mapping[str, Sequence[float]],
    ap: Mapping[str, Intervalo],
    *,
    n_bootstrap: int,
    semilla: int,
) -> tuple[str | None, str]:
    """El mejor PR-AUC, salvo que uno más simple no se distinga de él."""
    evaluados = [c for c in ORDEN_SIMPLICIDAD if c in ap] + sorted(
        c for c in ap if c not in ORDEN_SIMPLICIDAD and c not in BASELINES
    )
    if not evaluados:
        return None, "ningún candidato evaluable"
    mejor = max(evaluados, key=lambda c: (ap[c].valor, -evaluados.index(c)))
    for simple in evaluados[: evaluados.index(mejor)]:
        dif = diferencia_pareada(
            y, scores[mejor], scores[simple], n_bootstrap=n_bootstrap, semilla=semilla
        )
        if dif is not None and dif.bajo <= 0.0:
            return simple, (
                f"{mejor} tiene el mejor PR-AUC pero no se distingue de {simple} "
                f"({_fmt(dif)}): gana el más simple"
            )
    return mejor, f"{mejor} tiene el mejor PR-AUC"


def evaluar_nivel1(
    holdout: Sequence[CasoEval],
    scores: Mapping[str, Sequence[float]],
    bandas: Mapping[str, Bandas],
    *,
    sin_evaluar: Mapping[str, str] | None = None,
    n_bootstrap: int = N_BOOTSTRAP,
    semilla: int = SEMILLA_BOOTSTRAP,
) -> InformeNivel1:
    """Compara los candidatos con los baselines en el holdout y aplica el gate.

    Args:
        holdout: El ``holdout`` del golden humano, en el mismo orden que cada
            lista de ``scores``.
        scores: P(es TI) de cada candidato (``"A"``, ``"B"``, ``"A+B"``) sobre
            ``holdout``. Los baselines los calcula esta función.
        bandas: Los umbrales de cada candidato, elegidos en ``tune``
            (:func:`elegir_bandas`). Un candidato sin bandas no puede servir
            tres bandas y no se promociona.
        sin_evaluar: Candidatos que no llegaron a entrenarse y por qué (p. ej.
            B sin ``sentence-transformers``). Solo viajan al informe.
    """
    y = [c.es_ti for c in holdout]
    for nombre, s in scores.items():
        if len(s) != len(y):
            raise ValueError(f"{nombre}: {len(s)} scores para {len(y)} ejemplos")
    positivos = sum(1 for v in y if v)
    motivos: list[str] = []

    todos: dict[str, Sequence[float]] = dict(scores)
    for baseline in BASELINES:
        todos[baseline] = scores_baseline(holdout, baseline)

    ap: dict[str, Intervalo] = {}
    for nombre, s in todos.items():
        iv = ap_con_intervalo(y, s, n_bootstrap=n_bootstrap, semilla=semilla)
        if iv is not None:
            ap[nombre] = iv

    sobre_baselines: dict[str, dict[str, Intervalo]] = {}
    for candidato in scores:
        por_baseline: dict[str, Intervalo] = {}
        for baseline in BASELINES:
            dif = diferencia_pareada(
                y, scores[candidato], todos[baseline], n_bootstrap=n_bootstrap, semilla=semilla
            )
            if dif is not None:
                por_baseline[baseline] = dif
        sobre_baselines[candidato] = por_baseline

    indices_sub = [i for i, c in enumerate(holdout) if c.cpv_ti and not c.tiene_keyword]
    y_sub = [y[i] for i in indices_sub]
    pos_sub = sum(1 for v in y_sub if v)
    subpoblacion: dict[str, InformeSubpoblacion] = {}
    for candidato, s in scores.items():
        s_sub = [s[i] for i in indices_sub]
        subpoblacion[candidato] = InformeSubpoblacion(
            n=len(indices_sub),
            positivos=pos_sub,
            ap=ap_con_intervalo(y_sub, s_sub, n_bootstrap=n_bootstrap, semilla=semilla),
            sobre_prevalencia=diferencia_pareada(
                y_sub, s_sub, [1.0] * len(y_sub), n_bootstrap=n_bootstrap, semilla=semilla
            ),
        )

    bandas_holdout = {c: metricas_bandas(y, scores[c], b) for c, b in bandas.items() if c in scores}

    candidatos_ap = {c: iv for c, iv in ap.items() if c in scores}
    ganador, eleccion = _elegir(y, scores, candidatos_ap, n_bootstrap=n_bootstrap, semilla=semilla)

    if len(y) < MIN_HOLDOUT:
        motivos.append(f"holdout de {len(y)} ejemplos < {MIN_HOLDOUT}")
    if positivos == 0 or positivos == len(y):
        motivos.append("el holdout no tiene las dos clases")
    if ganador is None:
        motivos.append(eleccion)
    else:
        for baseline in BASELINES:
            dif = sobre_baselines[ganador].get(baseline)
            if dif is None:
                motivos.append(f"{ganador} sin comparación posible con {baseline}")
            elif dif.bajo <= 0.0:
                motivos.append(f"{ganador} no bate a {baseline}: {_fmt(dif)}")
        sub = subpoblacion[ganador]
        if pos_sub < MIN_SUBPOBLACION_POR_CLASE or (sub.n - pos_sub) < MIN_SUBPOBLACION_POR_CLASE:
            motivos.append(
                f"{SUBPOBLACION} sin soporte: {sub.n} ejemplos, {pos_sub} positivos "
                f"(mínimo {MIN_SUBPOBLACION_POR_CLASE} de cada clase)"
            )
        elif sub.sobre_prevalencia is None or sub.sobre_prevalencia.bajo <= 0.0:
            detalle = "" if sub.sobre_prevalencia is None else f": {_fmt(sub.sobre_prevalencia)}"
            motivos.append(f"{ganador} no supera a la prevalencia en {SUBPOBLACION}{detalle}")
        bandas_ganador = bandas.get(ganador)
        if bandas_ganador is None:
            motivos.append(f"{ganador} sin umbrales elegidos en tune")
        elif bandas_ganador.umbral_ti is None:
            motivos.append(
                f"{ganador}: ningún umbral llega a precisión {PRECISION_MIN_TI:.2f} en tune"
            )

    return InformeNivel1(
        n_holdout=len(y),
        positivos_holdout=positivos,
        ap=ap,
        sobre_baselines=sobre_baselines,
        subpoblacion=subpoblacion,
        bandas=dict(bandas),
        bandas_holdout=bandas_holdout,
        ganador=ganador,
        eleccion=eleccion,
        apto=not motivos,
        motivos=tuple(motivos),
        sin_evaluar=dict(sin_evaluar or {}),
    )


__all__ = [
    "BASELINES",
    "BASELINE_CPV",
    "BASELINE_KEYWORDS",
    "MIN_HOLDOUT",
    "MIN_SUBPOBLACION_POR_CLASE",
    "N_BOOTSTRAP",
    "ORDEN_SIMPLICIDAD",
    "PERDIDA_RECALL_MAX",
    "PRECISION_MIN_TI",
    "SUBPOBLACION",
    "Bandas",
    "CasoEval",
    "InformeNivel1",
    "InformeSubpoblacion",
    "Intervalo",
    "MetricasBandas",
    "ap_con_intervalo",
    "average_precision",
    "diferencia_pareada",
    "elegir_bandas",
    "evaluar_nivel1",
    "metricas_bandas",
    "scores_baseline",
]
