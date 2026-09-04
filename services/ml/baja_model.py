"""Modelo de baja ganadora — regresión cuantílica p10/p50/p90 (Fase 6.1).

Tres ``HistGradientBoostingRegressor`` con pérdida cuantílica: la predicción
de negocio es un **intervalo** ("baja esperada 12-18%, mediana 15%"), no un
punto — un punto sin incertidumbre invita a sobreconfianza en pujas.

El target es la baja **agregada por expediente** (una fila por licitación),
la misma magnitud que sirve ``predicciones_baja`` y que mide
``services.ml.calibration`` — ver ``db.repositories.ml_dataset``.

Validación **rolling-origin**: varios cortes temporales sucesivos en vez de un
único holdout de seis meses, cuyo resultado dependía de que ese semestre
concreto fuera representativo. El criterio de activación usa la media entre
folds. Baseline a batir: la media histórica suavizada del segmento
(``baja_media_organo_cpv4`` → ``baja_media_cpv4`` → ``baja_media_organo`` →
media global del train), que es lo que sirve ``baja_de_referencia``. Se compara
además con pérdida pinball en q=0.5 para las dos, porque el MAE lo minimiza la
mediana y enfrentar un p50 contra una *media* favorece al modelo.

Los folds se cortan por la fecha de **adjudicación**, que es cuando la etiqueta
pasa a ser observable. No contradice el ancla temporal único de
``services.ml.features`` —las features se siguen mirando desde la publicación,
en entrenamiento y en scoring—: son dos preguntas distintas. El ancla dice
"¿qué se sabía del mercado al publicar esta licitación?"; el corte del fold dice
"¿qué filas tenían ya resultado conocido en este instante?". Cortar el train por
publicación respondía a la segunda con la primera y le daba al modelo bajas que
todavía no habían ocurrido.

**Criterio de honestidad del RFC**: si el MAE(p50) no mejora el baseline ≥10%
relativo, la versión se registra pero NO se activa, y el serving sigue siendo
el baseline.

Los intervalos se **conformalizan** (split-CQR) sobre un bloque temporal que
el ajuste no vio: la cobertura del 80% pasa a cumplirse por construcción en vez
de depender de que los tres cuantiles salgan bien calibrados por su cuenta.

El **baseline** (:func:`predecir_baseline`, lo que se sirve mientras no haya
versión activa) se conformaliza igual, pero contra los pares
predicción↔realidad que él mismo generó en producción — ver
:func:`offset_conformal_baseline`. Su ±40% relativo original no tenía ninguna
garantía de cobertura pese a servirse como "p10-p90"; medido sobre 406 pares
cubría el 24%, no el 80%.

Registro en ``model_versions`` (name="baja_model") con métricas completas;
activación manual vía ``db.model_registry.activate_version`` o automática si
``ML_PRED_AUTO_ACTIVATE=true`` y se cumplen los criterios.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger
from services.ml.features import (
    CATEGORICAL_COLUMNS,
    FEATURE_COLUMNS,
    FilaDataset,
    _fecha_dt,
    construir_dataset_baja,
    fecha_valida,
)

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

log = get_logger(__name__)

MODEL_NAME = "baja_model"
QUANTILES = (0.10, 0.50, 0.90)
MIN_TRAIN_SAMPLES = 200
_MIN_VALID_SAMPLES = 30
_MODEL_PATH = Path(__file__).parents[2] / "data" / "models" / "baja_model.pkl"
# Tope físico del target: una baja real vive en [0, 1); el clip evita que
# outliers residuales empujen predicciones absurdas.
_BAJA_MAX = 0.95
# Semiancho relativo del intervalo del baseline antes de conformalizar (la
# heurística original: ±40% de la mediana). No es una cobertura, es una
# *forma*: lo que la convierte en un intervalo del 80% es el offset conformal.
_BASELINE_ANCHO_RELATIVO = 0.4
# Fracción de bajas realizadas negativas a partir de la cual el offset simétrico
# deja de ser inocuo: por encima, la cobertura se está comprando estirando el
# extremo superior porque el inferior no puede bajar de 0. Ver
# :func:`offset_conformal_baseline`.
_FRACCION_NEGATIVA_TOLERADA = 0.05
# Criterios de activación (acceptance del RFC).
MEJORA_MINIMA_RELATIVA = 0.10
COBERTURA_OBJETIVO = (0.75, 0.85)
# Cobertura nominal del intervalo servido (p10..p90).
_COBERTURA_NOMINAL = 0.80

_BASELINE_FALLBACK = ("baja_media_organo_cpv4", "baja_media_cpv4", "baja_media_organo")

# Techo de cardinalidad de una categórica nativa: HistGradientBoosting rechaza
# cualquier columna con más de ``max_bins`` (255) valores distintos.
MAX_CATEGORIAS = 255
# Bucket de cola larga cuando una columna supera el techo. El sentinel no puede
# colisionar con un valor real (CPV, CCAA, tipo de contrato…).
CATEGORIA_OTRAS = "__otras__"

# Hiperparámetros de partida (los que estuvieron fijos desde la Fase 6.1).
_HIPER_BASE: dict[str, Any] = {
    "max_iter": 300,
    "learning_rate": 0.06,
    "max_depth": 6,
    "min_samples_leaf": 30,
    "l2_regularization": 0.0,
}
# Rejilla de la búsqueda aleatoria. Se explora solo con q=0.5 y los ganadores
# se reutilizan en p10/p90: triplicar la búsqueda para afinar las colas no
# compensa en un reentrenamiento mensual.
_REJILLA: dict[str, list[Any]] = {
    "max_iter": [200, 300, 500],
    "learning_rate": [0.03, 0.06, 0.10],
    "max_depth": [4, 6, 8, None],
    "min_samples_leaf": [15, 30, 60],
    "l2_regularization": [0.0, 0.1, 1.0],
}


class FeatureSchemaMismatch(RuntimeError):
    """El artefacto se entrenó con otro conjunto (u orden) de columnas.

    ``BajaModel.predict`` construye la matriz con el ``FEATURE_COLUMNS`` del
    módulo, no con el que vio el ajuste. Si el ``.pkl`` activo es anterior a un
    cambio de features, sus árboles reciben columnas distintas en las mismas
    posiciones y devuelven números sin significado, en silencio. El serving
    trata esta excepción degradando al baseline (``services.ml.scoring``).
    """


@dataclass
class Prediccion:
    licitacion_id: str
    p10: float
    p50: float
    p90: float


def _aprender_categorias(filas: list[FilaDataset], col: str) -> dict[str, int]:
    """Mapa valor→ordinal de una columna categórica, acotado a ``MAX_CATEGORIAS``.

    ``HistGradientBoostingRegressor`` rechaza una categórica nativa con más de
    ``max_bins`` (255) valores distintos. En agosto de 2026 ``cpv4`` alcanzó
    1061 códigos y ``entrenar()`` empezó a morir con ``ValueError`` en cada
    pasada de la pipeline. El fallo era invisible desde CI —
    ``_run_post_ingestion_steps`` se traga la excepción y el run sale verde,
    con un email como único aviso — así que el modelo de baja se quedó
    congelado en su última versión mientras el scoring seguía sirviéndola.

    Se conservan los ``MAX_CATEGORIAS - 1`` valores más frecuentes y el resto
    cae en ``CATEGORIA_OTRAS``: la cola larga de CPV son códigos con un puñado
    de observaciones cada uno, sin señal propia para un árbol, y ``cpv2`` ya
    aporta la división gruesa. Lo mismo vale para ``organo`` y ``provincia``,
    que entraron después con cardinalidad alta por naturaleza. El orden es
    determinista (frecuencia desc, valor asc) para que dos entrenamientos sobre
    el mismo dataset den el mismo mapa.
    """
    frecuencias = Counter(str(f.features[col]) for f in filas)
    if len(frecuencias) <= MAX_CATEGORIAS:
        return {v: i for i, v in enumerate(sorted(frecuencias))}

    conservados = sorted(
        sorted(frecuencias, key=lambda v: (-frecuencias[v], v))[: MAX_CATEGORIAS - 1]
    )
    log.info(
        "baja_model_categorias_agrupadas",
        columna=col,
        distintos=len(frecuencias),
        conservados=len(conservados),
    )
    mapa = {v: i for i, v in enumerate(conservados)}
    mapa[CATEGORIA_OTRAS] = len(conservados)
    return mapa


def _codificar(
    filas: list[FilaDataset], categorias: dict[str, dict[str, int]] | None = None
) -> tuple[npt.NDArray[np.float64], dict[str, dict[str, int]]]:
    """Matriz numérica: categóricas por ordinal aprendido en train.

    Un valor no visto en entrenamiento va al bucket de cola larga si la columna
    se agrupó (``CATEGORIA_OTRAS``) y a ``-1`` si no. ``-1`` es una categoría
    desconocida para el ``OrdinalEncoder`` interno de sklearn, que la mapea a
    NaN → se trata como faltante. Los modelos serializados antes de que
    existiera el bucket no lo tienen en su mapa y conservan el comportamiento
    anterior sin reentrenar.
    """
    import numpy as np

    aprender = categorias is None
    cats: dict[str, dict[str, int]] = categorias if categorias is not None else {}
    if aprender:
        for col in CATEGORICAL_COLUMNS:
            cats[col] = _aprender_categorias(filas, col)

    X = np.full((len(filas), len(FEATURE_COLUMNS)), np.nan, dtype=np.float64)
    for i, fila in enumerate(filas):
        for j, col in enumerate(FEATURE_COLUMNS):
            valor = fila.features.get(col)
            if col in CATEGORICAL_COLUMNS:
                mapa = cats.get(col, {})
                X[i, j] = float(mapa.get(str(valor), mapa.get(CATEGORIA_OTRAS, -1)))
            elif valor is not None:
                X[i, j] = float(valor)
    return X, cats


def _columnas_observadas(X: npt.NDArray[np.float64]) -> tuple[list[bool], list[str]]:
    """``(máscara, nombres descartados)`` de las columnas con algún valor.

    ``HistGradientBoostingRegressor`` no admite una columna numérica **entera**
    a NaN: su binning intenta calcular los cortes sobre cero valores distintos
    y muere con ``ValueError: window shape cannot be larger than input array
    shape``, un mensaje que no dice nada del dato que lo provoca. El caso no es
    hipotético: basta con que una feature del segmento —``hhi_segmento``,
    ``plazo_dias``, cualquier agregado histórico— no tenga ni una observación
    en el corte que se está ajustando.

    Descartarla antes de ajustar es lo correcto además de lo que evita el
    crash: una columna sin un solo valor no aporta ningún split, así que el
    modelo resultante es el mismo. Lo que no puede pasar es que el
    entrenamiento **dependa** de que ninguna llegue vacía.
    """
    import numpy as np

    if X.shape[0] == 0:
        return [True] * X.shape[1], []
    observadas = ~np.all(np.isnan(X), axis=0)
    mask = [bool(v) for v in observadas]
    descartadas = [col for col, keep in zip(FEATURE_COLUMNS, mask, strict=True) if not keep]
    return mask, descartadas


def _aplicar_mascara(X: npt.NDArray[np.float64], mask: list[bool]) -> npt.NDArray[np.float64]:
    """Subconjunto de columnas de ``X`` según ``mask`` (sin copia si sobra todo)."""
    import numpy as np

    if all(mask):
        return X
    return X[:, np.array(mask, dtype=bool)]


def _filtrar(valores: list[bool], mask: list[bool]) -> list[bool]:
    """Aplica ``mask`` a una lista paralela a ``FEATURE_COLUMNS`` (p. ej. cat_mask)."""
    return [v for v, keep in zip(valores, mask, strict=True) if keep]


def _baseline(fila: FilaDataset, media_global: float) -> float:
    for col in _BASELINE_FALLBACK:
        valor = fila.features.get(col)
        if valor is not None:
            return float(valor)
    return media_global


def _pesos_recencia(filas: list[FilaDataset], halflife_meses: float) -> npt.NDArray[np.float64]:
    """Pesos que decaen con la antigüedad (vida media en meses).

    El drift de bajas está monitorizado (``services.ml.drift``) pero el ajuste
    trataba una adjudicación de hace cinco años igual que la del mes pasado.
    ``halflife_meses <= 0`` desactiva el decaimiento (pesos uniformes).
    """
    import numpy as np

    if halflife_meses <= 0 or not filas:
        return np.ones(len(filas), dtype=np.float64)
    fin = max(_fecha_dt(f.fecha) for f in filas)
    edades = np.array([(fin - _fecha_dt(f.fecha)).days / 30.0 for f in filas], dtype=np.float64)
    return np.power(0.5, edades / halflife_meses)


class BajaModel:
    """Tres regresores cuantílicos + codificación de categóricas + metadata."""

    def __init__(
        self,
        modelos: dict[float, Any],
        categorias: dict[str, dict[str, int]],
        metadata: dict[str, Any],
    ) -> None:
        self.modelos = modelos
        self.categorias = categorias
        self.metadata = metadata

    @property
    def conformal_offset(self) -> float:
        """Corrección de anchura del intervalo aprendida en calibración."""
        return float(self.metadata.get("conformal_offset") or 0.0)

    def verificar_features(self) -> None:
        """Comprueba que el artefacto se entrenó con las columnas actuales.

        Falla cerrado: un ``.pkl`` sin ``feature_columns`` en su metadata no se
        puede validar, y servir predicciones de un layout equivocado es peor
        que no servirlas (mismo criterio que el MISMATCH de sha256 en
        ``shared.model_integrity``).
        """
        registradas = self.metadata.get("feature_columns")
        if registradas is None:
            raise FeatureSchemaMismatch(
                f"El artefacto de {MODEL_NAME} no registra feature_columns; "
                "no se puede verificar contra el layout actual"
            )
        if tuple(registradas) != tuple(FEATURE_COLUMNS):
            faltan = sorted(set(FEATURE_COLUMNS) - set(registradas))
            sobran = sorted(set(registradas) - set(FEATURE_COLUMNS))
            raise FeatureSchemaMismatch(
                f"El artefacto de {MODEL_NAME} se entrenó con otras columnas "
                f"(faltan={faltan}, sobran={sobran}, n={len(registradas)} vs "
                f"{len(FEATURE_COLUMNS)}): reentrená antes de servirlo"
            )

    @property
    def mascara_features(self) -> list[bool]:
        """Columnas de :data:`FEATURE_COLUMNS` que el ajuste llegó a ver.

        Las que estaban **enteras a NaN** en el train se descartan antes de
        ajustar (:func:`_columnas_observadas`), así que la matriz de predicción
        tiene que recortarse igual o los árboles recibirían otras columnas en
        las mismas posiciones. Los artefactos anteriores a este cambio no
        registran la lista: para ellos la máscara es "todas", que es
        exactamente lo que hacían.
        """
        usadas = self.metadata.get("feature_columns_usadas")
        if not usadas:
            return [True] * len(FEATURE_COLUMNS)
        conjunto = {str(col) for col in usadas}
        return [col in conjunto for col in FEATURE_COLUMNS]

    def predict(self, filas: list[FilaDataset]) -> list[Prediccion]:
        if not filas:
            return []
        self.verificar_features()
        X_completa, _ = _codificar(filas, self.categorias)
        X = _aplicar_mascara(X_completa, self.mascara_features)
        por_quantil = {q: self.modelos[q].predict(X) for q in QUANTILES}
        offset = self.conformal_offset
        out: list[Prediccion] = []
        for i, fila in enumerate(filas):
            crudos = {q: float(por_quantil[q][i]) for q in QUANTILES}
            # El offset conformal ensancha (o estrecha, si sobraba anchura) el
            # intervalo; la mediana no se toca.
            ajustados = (crudos[0.10] - offset, crudos[0.50], crudos[0.90] + offset)
            # Monotonicidad: los tres fits son independientes y pueden cruzarse.
            p10, p50, p90 = sorted(min(max(v, 0.0), _BAJA_MAX) for v in ajustados)
            out.append(Prediccion(licitacion_id=fila.licitacion_id, p10=p10, p50=p50, p90=p90))
        return out

    def save(self, path: Path | None = None) -> Path:
        """Serializa el modelo con joblib + checksum SHA256 co-ubicado."""
        import joblib

        from shared.model_integrity import write_checksum

        target = path or _MODEL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, target, compress=3)
        write_checksum(target)
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> BajaModel:
        """Carga un modelo serializado con joblib. Lanza FileNotFoundError si no existe.

        Verifica la integridad del fichero (pin out-of-band ML_BAJA_MODEL_SHA256
        y/o checksum co-ubicado .sha256) antes de deserializar — ver
        ``shared.model_integrity`` para el razonamiento completo: joblib.load
        ejecuta código arbitrario, así que un .pkl manipulado es RCE.
        """
        import joblib

        from config import settings
        from shared.model_integrity import verify_model_integrity

        target = path or _MODEL_PATH
        if not target.exists():
            raise FileNotFoundError(f"No existe el modelo en {target}")

        verify_model_integrity(
            target,
            pinned_sha256=str(getattr(settings, "ML_BAJA_MODEL_SHA256", "") or ""),
            pin_setting_name="ML_BAJA_MODEL_SHA256",
            model_label=MODEL_NAME,
            env=str(getattr(settings, "ENV", "dev")),
        )

        obj = joblib.load(target)
        if not isinstance(obj, cls):
            raise TypeError(f"El archivo {target} no contiene un BajaModel")
        return obj


def _fechas_adjudicacion(hasta: str | None = None) -> dict[str, str]:
    """``licitacion_id`` → fecha de adjudicación (``YYYY-MM-DD``) del expediente.

    ``FilaDataset`` solo lleva el ancla de features —la publicación, acotada a
    no superar la adjudicación (``db.repositories.ml_dataset``)—, y los cortes
    temporales necesitan además el instante en el que la **etiqueta** pasó a ser
    observable. Sale del mismo repositorio y con el mismo filtro ``hasta`` que
    el dataset, así que ambas lecturas describen la misma población; el precio
    es una ejecución extra de la query agregada por entrenamiento (mensual).

    Lo natural sería que ``construir_dataset_baja`` devolviera esa fecha en la
    propia fila; eso es un cambio en ``services.ml.features``, fuera del alcance
    de este arreglo.
    """
    from db.repositories.ml_dataset import MlDatasetRepository

    return {
        str(row["id_externo"]): str(row["fecha_adjudicacion"])[:10]
        for row in MlDatasetRepository().pares_baja_agregada(hasta)
        if row.get("fecha_adjudicacion")
    }


def _fecha_label(fila: FilaDataset, fechas_label: Mapping[str, str]) -> datetime:
    """Instante en el que la etiqueta de ``fila`` pasó a ser observable.

    Es la fecha de adjudicación: la baja no existe antes de ella. Sin entrada en
    el mapa se cae al ancla de la fila, que es lo único disponible (y nunca
    posterior a la adjudicación, así que el fallback solo puede adelantar el
    corte, no retrasarlo).
    """
    return _fecha_dt(fechas_label.get(fila.licitacion_id) or fila.fecha)


def filtrar_fechas_invalidas(filas: list[FilaDataset]) -> tuple[list[FilaDataset], int]:
    """Descarta las filas cuya fecha no es parseable. Devuelve ``(filas, n)``.

    Las columnas de fecha son TEXT y la fuente cuela formatos que no son ISO
    (``'19-12-10'`` reventó el reentrenamiento mensual del 2026-09-01 dentro de
    :func:`_folds_rolling`). El parseo de :func:`_fecha_dt` es estricto **a
    propósito** —una fecha inventada mueve un corte temporal y con él la
    métrica—, pero abortar el entrenamiento entero por una fila es la reacción
    equivocada: el coste de perderla es una observación, y el de no entrenar es
    un mes sin modelo.

    Cada descarte se loguea con su id y su valor crudo, y el conteo viaja a las
    métricas del entrenamiento (``n_descartadas_fecha_invalida``): un descarte
    silencioso que crezca sin que nadie lo vea sería el mismo problema en
    versión lenta.
    """
    validas: list[FilaDataset] = []
    descartadas = 0
    for fila in filas:
        if fecha_valida(fila.fecha):
            validas.append(fila)
            continue
        descartadas += 1
        log.warning(
            "ml_dataset_fecha_invalida",
            licitacion_id=fila.licitacion_id,
            fecha=fila.fecha,
            campo="fecha_anchor",
        )
    return validas, descartadas


def sanear_fechas_label(fechas_label: Mapping[str, str]) -> tuple[dict[str, str], int]:
    """Quita del mapa de fechas de etiqueta las que no parsean.

    Mismo criterio que :func:`filtrar_fechas_invalidas`, pero aquí la fila **no
    se pierde**: sin entrada en el mapa, :func:`_fecha_label` cae al ancla de
    la fila, que es una fecha válida y nunca posterior a la adjudicación. Es
    justo el origen más probable de la basura, porque ``fecha_adjudicacion``
    llega cruda de ``adjudicaciones`` (TEXT, sin CHECK).
    """
    limpio: dict[str, str] = {}
    invalidas = 0
    for licitacion_id, fecha in fechas_label.items():
        if fecha_valida(fecha):
            limpio[licitacion_id] = fecha
            continue
        invalidas += 1
        log.warning(
            "ml_dataset_fecha_invalida",
            licitacion_id=licitacion_id,
            fecha=fecha,
            campo="fecha_adjudicacion",
        )
    return limpio, invalidas


def _split_temporal(
    filas: list[FilaDataset], valid_meses: int, fechas_label: Mapping[str, str]
) -> tuple[list[FilaDataset], list[FilaDataset]]:
    """Entrena hasta T, valida T..T+valid_meses (las filas llegan ordenadas).

    Mismo criterio asimétrico que :func:`_folds_rolling`: el train se filtra por
    la fecha en la que la etiqueta pasó a ser observable y el valid por el ancla
    de features.
    """
    corte = _fecha_dt(filas[-1].fecha) - timedelta(days=valid_meses * 30)
    train = [f for f in filas if _fecha_label(f, fechas_label) < corte]
    valid = [f for f in filas if _fecha_dt(f.fecha) >= corte]
    if len(train) < MIN_TRAIN_SAMPLES // 2 or len(valid) < _MIN_VALID_SAMPLES:
        # Histórico corto: split temporal 80/20 manteniendo el orden, con el
        # mismo embargo sobre el train (las filas aún sin adjudicar en el corte
        # no pueden entrenar). Si el embargo lo vacía —todas las etiquetas del
        # 80% inicial llegaron después del corte— se conserva el split sin
        # filtrar y se deja constancia: un train vacío no es un modelo peor,
        # es ningún modelo.
        k = int(len(filas) * 0.8)
        train, valid = filas[:k], filas[k:]
        if valid:
            corte_80 = _fecha_dt(valid[0].fecha)
            embargado = [f for f in train if _fecha_label(f, fechas_label) < corte_80]
            if embargado:
                train = embargado
            else:
                log.warning("baja_model_split_80_20_sin_embargo", n_train=len(train))
    return train, valid


def _folds_rolling(
    filas: list[FilaDataset],
    valid_meses: int,
    n_folds: int,
    fechas_label: Mapping[str, str],
) -> list[tuple[list[FilaDataset], list[FilaDataset]]]:
    """Cortes sucesivos con ventana de train expansiva (rolling origin).

    El fold más antiguo entrena con menos historia y valida el bloque
    siguiente; el más reciente entrena con todo menos el último bloque. Si el
    histórico no da para ningún fold válido, cae al split único de
    :func:`_split_temporal`, que es el comportamiento anterior.

    Los dos lados del corte usan fechas **distintas**, y es el arreglo de un bug
    real: el train son las filas cuya etiqueta ya era observable en el corte
    (``fecha_adjudicacion < inicio``) y el valid las publicadas en el bloque
    siguiente (``inicio <= ancla < límite``). Hasta 2026-08 los dos lados
    cortaban por el ancla —la publicación— y, como el ancla siempre precede a
    la adjudicación, el train se llevaba filas adjudicadas después del corte:
    el modelo veía en cada fold etiquetas que en ese instante no existían y la
    métrica describía un entrenamiento irrealizable en producción.

    Consecuencia buscada: las filas publicadas antes del corte pero adjudicadas
    después no caen en ningún lado de ese fold. No son train (su baja todavía no
    se conocía) ni test (ya estaban publicadas cuando empieza el bloque); son la
    banda de embargo que el rolling origin necesita para ser honesto.
    """
    fin = _fecha_dt(filas[-1].fecha)
    ancho = timedelta(days=valid_meses * 30)
    folds: list[tuple[list[FilaDataset], list[FilaDataset]]] = []
    for k in range(n_folds, 0, -1):
        inicio = fin - ancho * k
        limite = fin - ancho * (k - 1)
        train = [f for f in filas if _fecha_label(f, fechas_label) < inicio]
        valid = [f for f in filas if inicio <= _fecha_dt(f.fecha) < limite]
        if len(train) >= MIN_TRAIN_SAMPLES // 2 and len(valid) >= _MIN_VALID_SAMPLES:
            folds.append((train, valid))
    return folds or [_split_temporal(filas, valid_meses, fechas_label)]


def _fit_quantil(
    q: float,
    X: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    pesos: npt.NDArray[np.float64],
    cat_mask: list[bool],
    hiper: dict[str, Any],
) -> Any:
    from sklearn.ensemble import HistGradientBoostingRegressor

    est = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=q,
        categorical_features=cat_mask,
        random_state=42,
        **hiper,
    )
    est.fit(X, y, sample_weight=pesos)
    return est


def _combinaciones(n: int, semilla: int = 42) -> list[dict[str, Any]]:
    """``n`` combinaciones distintas de :data:`_REJILLA`, más la base.

    Determinista: dos entrenamientos sobre el mismo dataset exploran las mismas
    combinaciones y eligen la misma.
    """
    # S311: muestreo de hiperparámetros, no criptografía. La semilla fija es un
    # requisito aquí — dos entrenamientos del mismo dataset deben explorar lo
    # mismo y elegir lo mismo.
    rng = random.Random(semilla)  # noqa: S311
    combos: list[dict[str, Any]] = [dict(_HIPER_BASE)]
    vistas = {tuple(sorted(_HIPER_BASE.items(), key=lambda kv: kv[0]))}
    intentos = 0
    while len(combos) <= n and intentos < n * 20:
        intentos += 1
        combo = {k: rng.choice(v) for k, v in sorted(_REJILLA.items())}
        clave = tuple(sorted(combo.items(), key=lambda kv: kv[0]))
        if clave in vistas:
            continue
        vistas.add(clave)
        combos.append(combo)
    return combos


def _y_de(filas: list[FilaDataset]) -> npt.NDArray[np.float64]:
    import numpy as np

    return np.array([min(float(f.baja or 0.0), _BAJA_MAX) for f in filas], dtype=np.float64)


def _buscar_hiper(
    folds: list[tuple[list[FilaDataset], list[FilaDataset]]],
    cat_mask: list[bool],
    n_combos: int,
    halflife: float,
) -> tuple[dict[str, Any], int]:
    """Elige hiperparámetros por pinball(q=0.5) medio sobre los folds.

    Antes no había búsqueda: los cuatro valores estaban fijos en el código para
    los tres cuantiles. Se explora solo q=0.5 y el ganador se reutiliza en las
    colas. ``n_combos <= 0`` devuelve la base sin ajustar nada.
    """
    import numpy as np
    from sklearn.metrics import mean_pinball_loss

    if n_combos <= 0:
        return dict(_HIPER_BASE), 0

    combos = _combinaciones(n_combos)
    mejor: dict[str, Any] = dict(_HIPER_BASE)
    mejor_perdida = math.inf
    for combo in combos:
        perdidas: list[float] = []
        for train, valid in folds:
            X_tr_completa, cats = _codificar(train)
            X_va_completa, _ = _codificar(valid, cats)
            # La máscara sale del train de ESTE fold: un fold antiguo puede no
            # tener observaciones de una feature que el más reciente sí tiene.
            mask, _descartadas = _columnas_observadas(X_tr_completa)
            X_tr = _aplicar_mascara(X_tr_completa, mask)
            X_va = _aplicar_mascara(X_va_completa, mask)
            est = _fit_quantil(
                0.50,
                X_tr,
                _y_de(train),
                _pesos_recencia(train, halflife),
                _filtrar(cat_mask, mask),
                combo,
            )
            pred = np.clip(est.predict(X_va), 0.0, _BAJA_MAX)
            perdidas.append(float(mean_pinball_loss(_y_de(valid), pred, alpha=0.50)))
        media = sum(perdidas) / len(perdidas)
        if media < mejor_perdida:
            mejor_perdida, mejor = media, combo
    log.info("baja_model_hiper_elegidos", **mejor, pinball_p50=round(mejor_perdida, 5))
    return mejor, len(combos)


def _offset_conformal(
    p10: npt.NDArray[np.float64],
    p90: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    cobertura: float = _COBERTURA_NOMINAL,
) -> float:
    """Corrección split-CQR para que el intervalo cubra ``cobertura``.

    Score de conformidad de Romano et al.: ``E = max(p10 - y, y - p90)``, que es
    positivo cuando el punto queda fuera del intervalo y negativo cuando queda
    holgadamente dentro. El cuantil ``⌈(n+1)·cobertura⌉/n`` de esos scores es la
    cantidad que hay que sumar a cada extremo para alcanzar la cobertura
    deseada; puede ser **negativa**, y entonces estrecha un intervalo que
    sobraba de ancho. Esa simetría es lo que hace que la cobertura empírica
    aterrice en el objetivo en vez de simplemente superarlo.
    """
    import numpy as np

    if len(y) < _MIN_VALID_SAMPLES:
        return 0.0
    return _cuantil_conformal(np.maximum(p10 - y, y - p90), cobertura)


def _cuantil_conformal(scores: npt.NDArray[np.float64], cobertura: float) -> float:
    """Cuantil ``⌈(n+1)·cobertura⌉/n`` de los scores de conformidad.

    Extraído para que el modelo y el baseline usen literalmente la misma regla:
    lo que cambia entre los dos es cómo se construye el score, no el nivel al
    que se corta.
    """
    import numpy as np

    n = len(scores)
    nivel = min(1.0, math.ceil((n + 1) * cobertura) / n)
    return float(np.quantile(scores, nivel, method="higher"))


def _metricas_fold(
    modelos: dict[float, Any],
    valid: list[FilaDataset],
    X_valid: npt.NDArray[np.float64],
    media_global: float,
    mediana_train: float,
    offset: float,
) -> dict[str, float]:
    import numpy as np
    from sklearn.metrics import mean_absolute_error, mean_pinball_loss

    y = _y_de(valid)
    pred = {q: np.clip(modelos[q].predict(X_valid), 0.0, _BAJA_MAX) for q in QUANTILES}
    p10 = np.clip(
        np.minimum(pred[0.10], np.minimum(pred[0.50], pred[0.90])) - offset, 0.0, _BAJA_MAX
    )
    p90 = np.clip(
        np.maximum(pred[0.90], np.maximum(pred[0.50], pred[0.10])) + offset, 0.0, _BAJA_MAX
    )

    baseline = np.array([_baseline(f, media_global) for f in valid], dtype=np.float64)
    mae_p50 = float(mean_absolute_error(y, pred[0.50]))
    mae_baseline = float(mean_absolute_error(y, baseline))
    return {
        "mae_p50": mae_p50,
        "mae_baseline": mae_baseline,
        "mejora_relativa": (1.0 - mae_p50 / mae_baseline) if mae_baseline > 0 else 0.0,
        # Misma pérdida para modelo y baseline: el MAE lo minimiza la mediana,
        # así que enfrentar un p50 contra una media inclina la comparación.
        "pinball_p50": float(mean_pinball_loss(y, pred[0.50], alpha=0.50)),
        "pinball_p50_baseline": float(mean_pinball_loss(y, baseline, alpha=0.50)),
        # Suelo de cordura: predecir siempre la mediana del train. La mediana
        # sale del TRAIN, no del valid, para no mirar el target que se evalúa.
        "mae_mediana_constante": float(
            mean_absolute_error(y, np.full(len(y), mediana_train, dtype=np.float64))
        ),
        "pinball_p10": float(mean_pinball_loss(y, pred[0.10], alpha=0.10)),
        "pinball_p90": float(mean_pinball_loss(y, pred[0.90], alpha=0.90)),
        "cobertura_intervalo_80": float(np.mean((y >= p10) & (y <= p90))),
    }


def entrenar(
    *,
    hasta: str | None = None,
    valid_meses: int = 6,
    activar: bool | None = None,
    model_path: Path | None = None,
) -> dict[str, Any]:
    """Entrena p10/p50/p90, valida contra el baseline y registra la versión.

    Secuencia: filtra el target, elige hiperparámetros y mide con
    rolling-origin, ajusta el modelo final, **conformaliza** el intervalo sobre
    un bloque que el ajuste no vio y reporta la media de métricas entre folds.

    ``activar=None`` aplica la política del RFC: solo activa si
    ``ML_PRED_AUTO_ACTIVATE`` está encendido Y el modelo bate el baseline ≥10%
    relativo en MAE Y la cobertura del intervalo 80% nominal cae en [75, 85]%.
    Devuelve el resumen con métricas (clave ``activado``).
    """
    import numpy as np

    from config import settings

    filas_todas, _ = construir_dataset_baja(hasta=hasta)
    # Una fila con fecha no parseable no puede caer en ningún lado de un corte
    # temporal; se descarta con log en vez de abortar el entrenamiento (ver
    # `filtrar_fechas_invalidas`).
    filas_fechables, descartadas_fecha = filtrar_fechas_invalidas(filas_todas)
    # Una baja negativa (adjudicado por encima del presupuesto: modificados o
    # errores de fuente) sobrevivía en `y` porque el clip solo tenía techo,
    # mientras `predict` acota a [0, _BAJA_MAX]: esas filas tiraban de los tres
    # ajustes hacia una región que el modelo no puede predecir.
    filas = [f for f in filas_fechables if (f.baja or 0.0) >= 0.0]
    descartadas = len(filas_fechables) - len(filas)
    if len(filas) < MIN_TRAIN_SAMPLES:
        log.warning("baja_model_insufficient_data", n=len(filas), min=MIN_TRAIN_SAMPLES)
        return {"status": "datos_insuficientes", "n": len(filas)}

    halflife = float(getattr(settings, "ML_BAJA_HALFLIFE_MESES", 18.0))
    n_folds = int(getattr(settings, "ML_BAJA_FOLDS", 3))
    n_combos = int(getattr(settings, "ML_BAJA_SEARCH_COMBOS", 8))
    usar_conformal = bool(getattr(settings, "ML_BAJA_CONFORMAL", True))

    cat_mask = [col in CATEGORICAL_COLUMNS for col in FEATURE_COLUMNS]
    # Cuándo pasó a ser observable la etiqueta de cada fila: sin esto los folds
    # se cortan por la publicación y el train ve bajas del futuro.
    fechas_label, fechas_label_invalidas = sanear_fechas_label(_fechas_adjudicacion(hasta))
    folds = _folds_rolling(filas, valid_meses, n_folds, fechas_label)
    hiper, n_explorados = _buscar_hiper(folds, cat_mask, n_combos, halflife)

    # Bloque de calibración: el trozo inmediatamente anterior al último fold de
    # validación. El ajuste final no lo ve, así que el offset conformal y la
    # cobertura reportada no se miden sobre los mismos datos.
    train_final, valid_final = folds[-1]
    calibracion: list[FilaDataset] = []
    if usar_conformal and len(train_final) >= MIN_TRAIN_SAMPLES:
        corte_cal = _fecha_dt(valid_final[0].fecha) - timedelta(days=valid_meses * 30)
        # Mismo criterio asimétrico que los folds: ajusta lo que ya estaba
        # etiquetado en el corte y calibra sobre lo publicado después. Con el
        # corte por publicación en los dos lados, el offset conformal se medía
        # con un modelo que había visto bajas posteriores a su propio corte.
        ajuste = [f for f in train_final if _fecha_label(f, fechas_label) < corte_cal]
        candidata = [f for f in train_final if _fecha_dt(f.fecha) >= corte_cal]
        if len(ajuste) >= MIN_TRAIN_SAMPLES and len(candidata) >= _MIN_VALID_SAMPLES:
            train_final, calibracion = ajuste, candidata

    X_train_completa, categorias = _codificar(train_final)
    # Cobertura de features: una columna sin un solo valor observado en el
    # train no se puede binear y tumbaba el ajuste entero. Se descarta aquí,
    # se registra en la metadata del modelo (para que `predict` recorte igual)
    # y se reporta en las métricas.
    mask_features, features_descartadas = _columnas_observadas(X_train_completa)
    if features_descartadas:
        log.warning(
            "baja_model_features_sin_cobertura",
            descartadas=features_descartadas,
            n_train=len(train_final),
        )
    features_usadas = [
        col for col, keep in zip(FEATURE_COLUMNS, mask_features, strict=True) if keep
    ]
    X_train = _aplicar_mascara(X_train_completa, mask_features)
    cat_mask_usadas = _filtrar(cat_mask, mask_features)
    y_train = _y_de(train_final)
    pesos = _pesos_recencia(train_final, halflife)
    modelos: dict[float, Any] = {
        q: _fit_quantil(q, X_train, y_train, pesos, cat_mask_usadas, hiper) for q in QUANTILES
    }

    media_global = float(y_train.mean())
    offset = 0.0
    if calibracion:
        X_cal_completa, _ = _codificar(calibracion, categorias)
        X_cal = _aplicar_mascara(X_cal_completa, mask_features)
        pred_cal = {q: np.clip(modelos[q].predict(X_cal), 0.0, _BAJA_MAX) for q in QUANTILES}
        offset = _offset_conformal(
            np.minimum(pred_cal[0.10], pred_cal[0.50]),
            np.maximum(pred_cal[0.90], pred_cal[0.50]),
            _y_de(calibracion),
        )

    # Métricas por fold con los hiperparámetros elegidos. El último fold se
    # evalúa con el modelo que se va a serializar (no con uno reajustado sobre
    # más datos): si el bloque de calibración se separó del train, reajustar
    # daría métricas de un modelo distinto del que se guarda.
    por_fold: list[dict[str, float]] = []
    for i, (train, valid) in enumerate(folds):
        if i == len(folds) - 1:
            X_va_completa, _ = _codificar(valid, categorias)
            X_va = _aplicar_mascara(X_va_completa, mask_features)
            por_fold.append(
                _metricas_fold(
                    modelos, valid, X_va, media_global, float(np.median(y_train)), offset
                )
            )
            continue
        X_tr_completa, cats_f = _codificar(train)
        X_va_completa, _ = _codificar(valid, cats_f)
        mask_f, _descartadas_f = _columnas_observadas(X_tr_completa)
        X_tr = _aplicar_mascara(X_tr_completa, mask_f)
        X_va = _aplicar_mascara(X_va_completa, mask_f)
        y_tr = _y_de(train)
        modelos_f = {
            q: _fit_quantil(
                q,
                X_tr,
                y_tr,
                _pesos_recencia(train, halflife),
                _filtrar(cat_mask, mask_f),
                hiper,
            )
            for q in QUANTILES
        }
        por_fold.append(
            _metricas_fold(
                modelos_f, valid, X_va, float(y_tr.mean()), float(np.median(y_tr)), offset
            )
        )

    def _media(clave: str) -> float:
        return round(sum(f[clave] for f in por_fold) / len(por_fold), 5)

    def _desv(clave: str) -> float:
        valores = [f[clave] for f in por_fold]
        m = sum(valores) / len(valores)
        return round(math.sqrt(sum((v - m) ** 2 for v in valores) / len(valores)), 5)

    mejora = _media("mejora_relativa")
    cobertura = _media("cobertura_intervalo_80")
    metricas: dict[str, Any] = {
        "mae_p50": _media("mae_p50"),
        "mae_baseline": _media("mae_baseline"),
        "mejora_relativa": mejora,
        "pinball_p10": _media("pinball_p10"),
        "pinball_p50": _media("pinball_p50"),
        "pinball_p50_baseline": _media("pinball_p50_baseline"),
        "pinball_p90": _media("pinball_p90"),
        "mae_mediana_constante": _media("mae_mediana_constante"),
        "cobertura_intervalo_80": cobertura,
        "mae_p50_std_folds": _desv("mae_p50"),
        "cobertura_std_folds": _desv("cobertura_intervalo_80"),
        "n_folds": len(por_fold),
        "n_train": len(train_final),
        "n_valid": len(valid_final),
        "n_calibracion": len(calibracion),
        "n_descartadas_negativas": descartadas,
        # Filas que no entraron por tener una fecha que no parsea, y entradas
        # del mapa de fechas de adjudicación ignoradas por lo mismo. Un
        # descarte silencioso creciendo sin que nadie lo mire sería el mismo
        # problema que abortaba el entrenamiento, solo que en diferido.
        "n_descartadas_fecha_invalida": descartadas_fecha,
        "n_fechas_label_invalidas": fechas_label_invalidas,
        # Features que llegaron enteras a NaN al train final y quedaron fuera
        # del ajuste (ver `_columnas_observadas`).
        "features_descartadas_sin_cobertura": features_descartadas,
        "n_features_usadas": len(features_usadas),
        "conformal_offset": round(offset, 5),
        "hiper": hiper,
        "hiper_explorados": n_explorados,
        "halflife_meses": halflife,
        "valid_desde": valid_final[0].fecha,
        "valid_hasta": valid_final[-1].fecha,
        # Cardinalidad efectiva por columna categórica: es la métrica que se
        # acercó al techo de 255 sin que nadie la mirara hasta que reventó.
        "categorias": {col: len(categorias[col]) for col in CATEGORICAL_COLUMNS},
    }

    cumple = (
        mejora >= MEJORA_MINIMA_RELATIVA
        and COBERTURA_OBJETIVO[0] <= cobertura <= COBERTURA_OBJETIVO[1]
    )
    if activar is None:
        activar = bool(getattr(settings, "ML_PRED_AUTO_ACTIVATE", False)) and cumple

    modelo = BajaModel(
        modelos,
        categorias,
        metadata={
            # Layout completo con el que se construyó la matriz (lo verifica
            # `verificar_features` contra FEATURE_COLUMNS).
            "feature_columns": list(FEATURE_COLUMNS),
            # Subconjunto que el ajuste llegó a ver: `predict` recorta por él.
            "feature_columns_usadas": features_usadas,
            "feature_columns_descartadas": features_descartadas,
            "conformal_offset": offset,
            "metrics": metricas,
        },
    )
    path = modelo.save(model_path)
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    from db.model_registry import register_version

    version = register_version(
        name=MODEL_NAME,
        path=str(path),
        sha256=sha256,
        metrics=metricas,
        n_samples=len(train_final),
        activate=bool(activar),
        notes="cumple criterios RFC 20260611-2" if cumple else "NO bate baseline — no activar",
    )
    log.info(
        "baja_model_trained",
        version=version,
        activado=bool(activar),
        cumple_criterios=cumple,
        **{k: v for k, v in metricas.items() if isinstance(v, int | float)},
    )
    return {
        "status": "ok",
        "version": version,
        "activado": bool(activar),
        "cumple_criterios": cumple,
        "path": str(path),
        **metricas,
    }


def intervalo_baseline(p50: float, offset: float = 0.0) -> tuple[float, float]:
    """Intervalo del baseline alrededor de ``p50``, con corrección conformal.

    Punto único donde vive la regla del ±40%: la usan el serving
    (:func:`predecir_baseline`) y la calibración
    (:func:`offset_conformal_baseline`). Medir el score de conformidad contra
    una anchura distinta de la que se sirve daría un offset que no corrige lo
    que se está sirviendo, así que las dos entran por aquí.

    ``offset`` ensancha ambos extremos (o los estrecha, si es negativo). La
    mediana no se toca — es exactamente lo que permite reconstruir el intervalo
    *crudo* de una fila ya servida a partir de su ``p50`` almacenado, y por
    tanto recalcular el offset cada noche sin acumularlo sobre sí mismo. El
    ``min``/``max`` final mantiene ``p10 <= p50 <= p90`` incluso con un offset
    lo bastante negativo como para cruzar los extremos.
    """
    ancho = p50 * _BASELINE_ANCHO_RELATIVO + offset
    p10 = min(max(p50 - ancho, 0.0), p50)
    p90 = max(min(p50 + ancho, _BAJA_MAX), p50)
    return p10, p90


def offset_conformal_baseline(pares: list[tuple[float, float]]) -> float:
    """Corrección split-conformal para que el intervalo del baseline cubra el 80%.

    ``pares`` son ``(p50_servido, baja_realizada)`` ya resueltos
    (``MlDatasetRepository.pares_baseline_resueltos``, que los mide con la misma
    regla de denominador que el target). El score se calcula contra el intervalo
    crudo reconstruido desde ``p50``, no contra el que se guardó: así la
    corrección es idempotente y converge en vez de congelarse.

    Misma matemática que la del modelo (:func:`_offset_conformal`): un baseline
    que dice "p10-p90" tiene que ganarse ese nombre igual que se lo gana el
    modelo. Devuelve ``0.0`` con menos de :data:`_MIN_VALID_SAMPLES` pares —
    sin muestra suficiente la corrección sería ruido, y ensanchar por ruido
    engaña tanto como no ensanchar.

    Validez: split-conformal supone intercambiabilidad, y aquí los pares son
    adjudicaciones pasadas frente a licitaciones abiertas. Es el mismo supuesto
    —y la misma exposición al drift— que la conformalización del modelo sobre
    un bloque temporal held-out; ``services.ml.drift`` es lo que vigila que
    siga siendo razonable.
    """
    import numpy as np

    if len(pares) < _MIN_VALID_SAMPLES:
        return 0.0

    crudos = [intervalo_baseline(p50) for p50, _ in pares]
    lo = np.array([c[0] for c in crudos], dtype=np.float64)
    hi = np.array([c[1] for c in crudos], dtype=np.float64)
    y = np.array([realizada for _, realizada in pares], dtype=np.float64)

    # Score de Romano: cuánto hay que sumar a cada extremo para meter el punto.
    scores = np.maximum(lo - y, y - hi)
    # ...salvo que ningún offset pueda meterlo. ``intervalo_baseline`` clipa a
    # [0, _BAJA_MAX], mientras que la baja realizada que mide el closed-loop
    # admite valores **negativos** (sobrecoste: se adjudica por encima del
    # presupuesto, hasta la tolerancia de ``db.repositories.ml_dataset``). Esos
    # pares quedan fuera por mucho que se ensanche, y contarlos como si un
    # offset mayor fuera a capturarlos es lo que hace que el cuantil se quede
    # corto: la cobertura servida aterrizaría por debajo de la nominal.
    alcanzable = (y >= 0.0) & (y <= _BAJA_MAX)
    scores = np.where(alcanzable, scores, np.inf)

    offset = _cuantil_conformal(scores, _COBERTURA_NOMINAL)
    if not math.isfinite(offset):
        # Ni ensanchando al máximo se alcanza la nominal sin permitir p10 < 0.
        # Se sirve entonces el offset más pequeño que captura todos los pares
        # capturables -- la cobertura máxima alcanzable bajo este contrato, sin
        # inflar el intervalo más allá de eso, que no compraría ni un par más.
        # El hueco contra la nominal lo reporta el monitor de calibración, que
        # es la lectura correcta: fingir un 80% imposible sería peor.
        finitos = scores[np.isfinite(scores)]
        offset = float(finitos.max()) if finitos.size else 0.0

    n_bajo_cero = int((y < 0.0).sum())
    servidos = [intervalo_baseline(p50, offset) for p50, _ in pares]
    cubierto = (y >= np.array([lo for lo, _ in servidos])) & (
        y <= np.array([hi for _, hi in servidos])
    )

    # Este evento es el que hace falta para decidir si ``p10`` debe poder ser
    # negativo, y por eso se emite siempre, no solo cuando algo falla.
    #
    # El offset es **simétrico** (Romano et al., igual que el del modelo), pero
    # el extremo inferior está clipado a 0 mientras que la baja realizada puede
    # ser negativa. Cuando eso pasa, la cobertura se compra estirando solo el
    # extremo superior: se alcanza el 80% nominal, sí, pero ``p90`` acaba muy
    # por encima del percentil 90 real y deja de significar lo que dice. Es una
    # degradación distinta de la que arregla este offset y no se puede resolver
    # sin decidir si el contrato admite ``p10 < 0`` -- decisión de producto,
    # no del monitor.
    evento = {
        "n": len(pares),
        "offset": offset,
        "cobertura_calibracion": float(cubierto.mean()),
        "cobertura_nominal": _COBERTURA_NOMINAL,
        "cobertura_maxima_con_p10_no_negativo": float(alcanzable.mean()),
        "n_realizada_negativa": n_bajo_cero,
    }
    if n_bajo_cero / len(pares) > _FRACCION_NEGATIVA_TOLERADA:
        log.warning("baja_baseline_conformal_asimetria_por_clip", **evento)
    else:
        log.info("baja_baseline_conformal", **evento)
    return offset


def predecir_baseline(
    filas: list[FilaDataset], media_global: float = 0.12, offset: float = 0.0
) -> list[Prediccion]:
    """Serving honesto cuando no hay modelo activo: la media del segmento como
    p50 y el intervalo del ±40% relativo **conformalizado** con ``offset``.

    Con ``offset=0.0`` sale la heurística original, que no tiene ninguna
    garantía de cobertura: llamar p10/p90 a sus extremos prometía un 80% que
    nadie había medido. ``offset`` es lo que :func:`offset_conformal_baseline`
    calcula sobre pares ya resueltos y lo que convierte esa forma en un
    intervalo del 80% de verdad.
    """
    out: list[Prediccion] = []
    for fila in filas:
        p50 = min(max(_baseline(fila, media_global), 0.0), _BAJA_MAX)
        p10, p90 = intervalo_baseline(p50, offset)
        out.append(Prediccion(licitacion_id=fila.licitacion_id, p10=p10, p50=p50, p90=p90))
    return out
