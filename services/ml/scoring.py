"""Scoring batch de predicciones (Fase 6, RFC 20260611-2).

Serving = batch nocturno + lectura de tabla (patrón ``ml_proba``): nada de
inferencia online por request. Idempotente: clave natural + upsert
(``ON CONFLICT ... DO UPDATE``) — doble
ejecución produce las mismas filas. En ``predicciones_baja`` la clave son los
dos únicos parciales de v140 (expediente, o expediente + ``lote_numero``), y el
upsert vive en ``PrediccionesRepository.guardar_baja``. En
``predicciones_retencion`` la clave es el expediente, y
``PrediccionesRepository.guardar_retencion`` purga además lo que la corrida no
refrescó. El módulo no abre conexiones: todo su SQL vive en ``db/`` (ADR-022).

Si no hay versión activa del modelo en ``model_versions`` (no entrenado aún,
o el entrenamiento no batió al baseline — criterio de honestidad), se sirve
el **baseline** de medias históricas del segmento con ``model_version NULL``:
el frontend puede distinguirlo y etiquetarlo como estimación histórica.

Ese baseline también **conformaliza** su intervalo (``_offset_baseline``). Su
±40% relativo era una forma sin garantía de cobertura, servida bajo el nombre
p10/p90 que promete un 80%: en producción cubría el 24%. Ahora la anchura sale
de los pares predicción↔realidad que el propio baseline ya generó, con la misma
matemática split-conformal que usa el modelo.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from db.database import now_utc_iso
from db.repositories.predicciones import PrediccionesRepository
from db.repositories.renovaciones import HORIZONTE_RENOVACIONES_MAX_MESES
from observability.logging import get_logger
from services.dedupe import normalize_organo
from services.ml.baja_model import (
    MODEL_NAME,
    MODEL_NAME_LOTE,
    BajaModel,
    FeatureSchemaMismatch,
    Prediccion,
    predecir_baseline,
)
from services.ml.features import FilaDataset, features_licitaciones_abiertas

if TYPE_CHECKING:
    from services.ml.retencion_labels import EtiquetasPorSegmento, ParRetencion

log = get_logger(__name__)


def _media_global_baja(*, por_lote: bool = False) -> float:
    """Baja media histórica, usada como baseline sin modelo entrenado.

    Delega en ``db.repositories.ml_dataset`` para compartir la regla de
    denominador con el target de entrenamiento y con ``calibration.py``: antes
    promediaba bajas **por lote** mientras el modelo predice la baja
    **agregada por expediente**, así que el baseline y el modelo no medían la
    misma magnitud. ``por_lote=True`` es el caso simétrico: el baseline del
    batch por lote promedia bajas por lote, que es lo que ese batch predice.
    """
    from db.repositories.ml_dataset import MlDatasetRepository

    return MlDatasetRepository().media_global_baja(por_lote=por_lote)


def _offset_baseline(*, por_lote: bool = False) -> float:
    """Corrección conformal del intervalo del baseline, sobre pares ya resueltos.

    Sin esto el baseline servía un ±40% relativo que no cubría el 80% que su
    nombre (p10/p90) promete: medido en producción sobre 406 pares, cubría el
    24%. El offset lo mide contra la realidad y lo corrige.

    Fail-open como el resto del closed-loop: si la agregación falla se sirve el
    intervalo crudo en vez de no servir nada. Se loguea el fallo, porque un 0
    por error y un 0 por falta de pares se leen igual en la tabla y no son lo
    mismo.
    """
    from db.repositories.ml_dataset import MlDatasetRepository
    from services.ml.baja_model import offset_conformal_baseline

    try:
        return offset_conformal_baseline(
            MlDatasetRepository().pares_baseline_resueltos(por_lote=por_lote)
        )
    except Exception as exc:
        log.warning("baja_baseline_conformal_failed", error=str(exc), por_lote=por_lote)
        return 0.0


def score_predicciones_baja(
    *, limit: int = 5000, filas: list[FilaDataset] | None = None
) -> dict[str, Any]:
    """Puntúa las licitaciones abiertas y materializa ``predicciones_baja``.

    Escribe la fila **agregada** de cada expediente (``lote_numero`` NULL), que
    es la que se sirve por defecto. Las filas por lote las escribe
    :func:`score_predicciones_baja_por_lote`, aparte y solo con
    ``ML_BAJA_POR_LOTE``.

    ``filas`` permite pasar las features ya construidas
    (:func:`~services.ml.features.features_licitaciones_abiertas`): el job
    nocturno las necesita también para el monitor de drift, y construirlas
    dos veces era cargar dos veces el histórico entero. Sin ellas se
    construyen aquí, con ``limit``.
    """
    return _score_baja(limit=limit, por_lote=False, filas=filas)


def score_predicciones_baja_por_lote(*, limit: int = 5000) -> dict[str, Any]:
    """Materializa una predicción **por lote** de las licitaciones abiertas (v140).

    Cada lote publicado con presupuesto recibe su fila (``lote_numero`` no
    nulo), junto a la agregada del expediente, que no se toca. La sirve el
    modelo :data:`~services.ml.baja_model.MODEL_NAME_LOTE` si hay versión
    activa y, si no, el baseline histórico calculado **por lote** (medias y
    anchura conformal sobre pares por lote): el mismo criterio de honestidad
    que el agregado, a su granularidad.

    No sustituye a nada: la vista del expediente sigue sirviendo el agregado,
    y la de un lote ya prefería la fila del lote cuando existía
    (``prediccion_ambito``). Por eso el job solo lo llama con
    ``ML_BAJA_POR_LOTE`` encendido: la decisión de encenderlo es la que
    informa ``scripts/comparar_baja_por_lote.py``.
    """
    return _score_baja(limit=limit, por_lote=True)


def _score_baja(
    *, limit: int, por_lote: bool, filas: list[FilaDataset] | None = None
) -> dict[str, Any]:
    """Cuerpo común de los dos batches de baja; ver sus docstrings."""
    if filas is None:
        filas = (
            features_licitaciones_abiertas(limit=limit, por_lote=True)
            if por_lote
            else features_licitaciones_abiertas(limit=limit)
        )
    granularidad = "lote" if por_lote else "expediente"
    if not filas:
        log.info("baja_scoring_skip", reason="sin_licitaciones_abiertas", granularidad=granularidad)
        return {"status": "sin_abiertas", "filas": 0, "granularidad": granularidad}

    from db.model_registry import get_active
    from shared.model_artifacts import resolve_active_artifact

    # resolve_active_artifact verifica el sha256 registrado (y descarga el
    # asset de la Release si el runner efímero no tiene el fichero). Un
    # artefacto irresoluble degrada a baseline; un MISMATCH propaga — servir
    # predicciones de un artefacto equivocado es peor que no servirlas.
    nombre = MODEL_NAME_LOTE if por_lote else MODEL_NAME
    activa = get_active(nombre)
    artefacto = resolve_active_artifact(nombre) if activa else None
    preds: list[Prediccion] | None = None
    version: int | None = None
    # Distingue el baseline legítimo (no hay versión activa: el RFC lo sirve a
    # propósito) del baseline **degradado** (hay versión activa pero no se pudo
    # servir). Los dos escriben las mismas filas y hasta 2026-08 los dos salían
    # como `status: ok`, así que el batch pasaba en verde mientras el modelo
    # activo llevaba semanas sin llegar a producción. El CLI usa este campo
    # para poner el job en rojo y alertar.
    degradado: str | None = None
    # Solo tiene valor en el camino baseline; en el del modelo la
    # conformalización ya viene dentro del artefacto (`conformal_offset`).
    offset_baseline: float | None = None
    if activa and artefacto is not None:
        modelo = BajaModel.load(artefacto, por_lote=True) if por_lote else BajaModel.load(artefacto)
        try:
            preds = modelo.predict(filas)
            version = int(activa["version"])
        except FeatureSchemaMismatch as exc:
            # El artefacto activo se entrenó con otro layout de columnas: sus
            # árboles recibirían features distintas en las mismas posiciones y
            # devolverían números sin significado. Degradar al baseline (que la
            # UI ya etiqueta como estimación histórica) es la única opción
            # honesta hasta que corra el reentrenamiento.
            log.warning(
                "baja_model_feature_schema_mismatch",
                version=int(activa["version"]),
                error=str(exc),
            )
            degradado = "feature_schema_mismatch"
    if preds is None:
        if activa and artefacto is None:
            log.warning("baja_model_artifact_unresolvable_fallback_baseline")
            degradado = "artefacto_irresoluble"
        if por_lote:
            offset_baseline = _offset_baseline(por_lote=True)
            media = _media_global_baja(por_lote=True)
        else:
            offset_baseline = _offset_baseline()
            media = _media_global_baja()
        preds = predecir_baseline(filas, media, offset_baseline)
        version = None

    computed_at = now_utc_iso()
    PrediccionesRepository().guardar_baja(
        [
            (
                p.licitacion_id,
                # En el batch agregado se fuerza NULL aunque la fila trajera
                # lote: la unicidad agregada es justo la que protege este NULL.
                p.lote_numero if por_lote else None,
                round(p.p10, 5),
                round(p.p50, 5),
                round(p.p90, 5),
                version,
                computed_at,
            )
            for p in preds
        ]
    )
    log.info(
        "baja_scoring_done",
        granularidad=granularidad,
        filas=len(preds),
        model_version=version,
        serving="modelo" if version else "baseline",
        degradado=degradado,
        conformal_offset_baseline=offset_baseline,
    )
    return {
        "status": "ok",
        "granularidad": granularidad,
        "filas": len(preds),
        "model_version": version,
        "serving": "modelo" if version else "baseline",
        "degradado": degradado,
        "conformal_offset_baseline": offset_baseline,
        "computed_at": computed_at,
    }


# ── Retención ─────────────────────────────────────────────────────────────

# Fuerza del shrinkage del baseline de retención: cuántos pares «pesa» la tasa
# del nivel de arriba frente a los del propio nivel. Misma filosofía que
# ``services.ml.features._SHRINKAGE_K_DEFECTO`` (el target encoding del modelo
# de baja), pero constante propia: son dos estimadores distintos, y afinar uno
# no debe mover el otro.
_SHRINKAGE_K_RETENCION = 10.0

# Probabilidad de retención que se sirve cuando no hay NINGÚN par etiquetado:
# BD recién sembrada, o el emparejamiento falló (:func:`_etiquetas_retencion` es
# fail-open). Es el «default conservador» que el baseline ya servía en ese
# caso: sin pares no hay tasa global hacia la que encoger, y un 0.6 fijo
# —riesgo de cambio 0.4 para todos— no ordena nada, pero tampoco se inventa un
# segmento. Se conserva tal cual para no cambiar a la vez el caso degenerado.
_PROB_RETENCION_SIN_PARES = 0.6


@dataclass(frozen=True)
class _BaselineRetencion:
    """Tasa de retención por nivel, con shrinkage jerárquico empirical-Bayes.

    Tres niveles: global, CPV-4 y segmento ``(órgano normalizado, CPV-4)``. Cada
    uno se encoge hacia el de arriba con fuerza ``k``
    (:data:`_SHRINKAGE_K_RETENCION`), así que un segmento con pocos pares se
    parece a su CPV-4 y uno con muchos, a sí mismo. Ver
    :func:`_baseline_retencion`.
    """

    tasa_global: float
    por_cpv4: dict[str, float]
    por_segmento: dict[tuple[str, str], float]
    pares: int

    def tasa(self, organo_n: str | None, cpv4: str | None) -> tuple[float, str]:
        """``(tasa, nivel)``: la del segmento si existe; si no, la del CPV-4; si no, la global."""
        if organo_n and cpv4 and (organo_n, cpv4) in self.por_segmento:
            return self.por_segmento[(organo_n, cpv4)], "segmento"
        if cpv4 and cpv4 in self.por_cpv4:
            return self.por_cpv4[cpv4], "cpv4"
        return self.tasa_global, "global"


def _baseline_retencion(
    etiquetas: EtiquetasPorSegmento | None, *, k: float = _SHRINKAGE_K_RETENCION
) -> _BaselineRetencion:
    """Tasas del baseline a partir de los pares etiquetados, con shrinkage.

    - global: ``p_g = Σ labels / N`` sobre TODOS los pares, agregada;
    - CPV-4: ``p_c = (Σ_c + k·p_g) / (n_c + k)``;
    - segmento: ``p_s = (Σ_s + k·p_c) / (n_s + k)``.

    Sustituye al corte anterior: los segmentos con ``MIN_OBS_SEGMENTO`` pares o
    más servían su tasa cruda y el resto una media **no ponderada** de las
    tasas publicadas. Era un escalón —con 5 pares se pasaba de la media a un
    0.0 o un 1.0— y la media pesaba igual un segmento de 5 pares que uno de
    500. El 2026-09-24 dejaba fuera 1.076 segmentos frente a 208 publicados.

    Caso degenerado, sin ningún par: :data:`_PROB_RETENCION_SIN_PARES` para
    todos.
    """
    conteos = etiquetas.conteos if etiquetas is not None else {}
    n_total = sum(n for _, n in conteos.values())
    if n_total == 0:
        log.info("retencion_baseline_estructura", pares=0, tasa_global=_PROB_RETENCION_SIN_PARES)
        return _BaselineRetencion(
            tasa_global=_PROB_RETENCION_SIN_PARES, por_cpv4={}, por_segmento={}, pares=0
        )

    tasa_global = sum(retenidos for retenidos, _ in conteos.values()) / n_total
    retenidos_cpv4: Counter[str] = Counter()
    pares_cpv4: Counter[str] = Counter()
    for (_, cpv4), (retenidos, pares) in conteos.items():
        retenidos_cpv4[cpv4] += retenidos
        pares_cpv4[cpv4] += pares
    por_cpv4 = {
        cpv4: (retenidos_cpv4[cpv4] + k * tasa_global) / (n + k) for cpv4, n in pares_cpv4.items()
    }
    por_segmento = {
        (organo_n, cpv4): (retenidos + k * por_cpv4[cpv4]) / (pares + k)
        for (organo_n, cpv4), (retenidos, pares) in conteos.items()
    }
    log.info(
        "retencion_baseline_estructura",
        pares=n_total,
        segmentos=len(por_segmento),
        cpv4s=len(por_cpv4),
        tasa_global=round(tasa_global, 4),
        k=k,
    )
    return _BaselineRetencion(
        tasa_global=tasa_global, por_cpv4=por_cpv4, por_segmento=por_segmento, pares=n_total
    )


def _etiquetas_retencion(adjudicaciones: list[dict[str, Any]]) -> EtiquetasPorSegmento | None:
    """Emparejamiento del histórico (tasas del baseline y resueltos), fail-open.

    Mide lo mismo que entrena el modelo: ``AVG(label)`` sobre los MISMOS pares
    vencimiento→sucesora. Hasta 2026-08 el baseline contaba en su lugar
    adjudicaciones con ``empresa_id`` no nulo sobre el total del segmento —la
    tasa de vinculación al maestro de empresas, ≈1 en cuanto la resolución de
    entidades funciona— bajo un docstring que prometía retención: un riesgo de
    cambio constante y falsamente bajo, escrito cada noche. El baseline tiene
    que medir la magnitud que sustituye, o compararlo con el modelo no
    significa nada (el mismo criterio que :func:`_media_global_baja`).

    Si el emparejamiento falla devuelve ``None``: el baseline cae a su caso
    degenerado y los resueltos quedan sin detectar, en vez de no publicar nada.
    """
    from services.ml import retencion_labels

    try:
        return retencion_labels.etiquetas_por_segmento(adjudicaciones)
    except Exception as exc:
        log.warning("retencion_baseline_error", error=str(exc))
        return None


def _separar_resueltos(
    filas: list[ParRetencion], etiquetas: EtiquetasPorSegmento | None, *, excluir: bool
) -> tuple[list[ParRetencion], int | None, int]:
    """``(filas que se puntúan, resueltos detectados, excluidos)``.

    Un vencimiento está **resuelto** si su sucesora ya está adjudicada según la
    MISMA heurística que etiqueta los pares de entrenamiento
    (``retencion_labels._emparejar``): su riesgo ya no es una predicción. Se
    detectan y se cuentan siempre, y se excluyen solo con
    ``ML_RETENCION_EXCLUIR_RESUELTOS``. La heurística da falsos positivos en
    segmentos con mucha actividad (un contrato paralelo del mismo órgano y
    CPV-4 pasa por sucesora), y excluir un contrato no es neutro: sin fila, su
    ``riesgo_cambio`` es NULL y el orden «score» de Renovaciones lo manda al
    fondo con score 0. Encender el flag exige antes auditar una muestra de los
    resueltos a mano, como ``scripts/audit_retencion.py`` hace con los pares.

    ``None`` en detectados si el emparejamiento falló: no es lo mismo no haber
    encontrado ninguno que no haber podido buscarlos.
    """
    if etiquetas is None:
        return filas, None, 0
    resueltos = {f.licitacion_id for f in filas if f.licitacion_id in etiquetas.con_sucesora}
    if not excluir:
        return filas, len(resueltos), 0
    return [f for f in filas if f.licitacion_id not in resueltos], len(resueltos), len(resueltos)


def score_predicciones_retencion(
    *, months_ahead: int = HORIZONTE_RENOVACIONES_MAX_MESES
) -> dict[str, Any]:
    """Puntúa el riesgo de cambio de manos de los contratos que vencen pronto.

    Población: contratos con empresa del maestro cuyo fin efectivo cae en los
    próximos ``months_ahead`` meses, con la misma ventana que la vista de
    Renovaciones (``retencion_labels.ventana_vencimientos``). El default es
    ``HORIZONTE_RENOVACIONES_MAX_MESES``, el tope que admite ``GET
    /renovaciones``: hasta 2026-09 el batch puntuaba 12 meses y la ruta servía
    hasta 60, así que más allá del año todo salía con ``riesgo_cambio`` NULL y
    score 0 en el orden «score».

    El histórico de adjudicaciones se carga **una vez** y lo comparten la
    población, el emparejamiento (tasas y resueltos) y, con modelo, las
    features. El 2026-09-24 se cargaba dos veces, y las features se calculaban
    aunque no hubiera modelo que las leyera: ~10 min 40 s de un step de 1.049 s.

    Con versión activa del modelo sirve el modelo, y solo entonces calcula
    features. Sin ella, el **baseline**: la tasa histórica de retención del
    segmento con shrinkage jerárquico (:func:`_baseline_retencion`). En la
    tabla el baseline se escribe con ``model_version`` NULL, que es lo que la
    UI distingue; en el dict de resultado sale ``model_version="baseline"``,
    como siempre, para quien lo lee desde el CLI.

    Los vencimientos ya resueltos se cuentan siempre y solo se excluyen con
    ``ML_RETENCION_EXCLUIR_RESUELTOS`` (:func:`_separar_resueltos`). La
    escritura (``PrediccionesRepository.guardar_retencion``) purga en la misma
    transacción las filas que esta corrida no refrescó: ``purgadas``.
    """
    from config import settings
    from db.model_registry import get_active
    from services.ml import retencion_labels
    from shared.model_artifacts import resolve_active_artifact

    activa = get_active("retencion_model")
    artefacto = resolve_active_artifact("retencion_model") if activa else None
    # Ver la nota de `degradado` en _score_baja: el baseline por falta de
    # modelo activo es el contrato del RFC; el baseline con modelo activo
    # irresoluble es una avería que debe verse.
    degradado: str | None = None
    if activa and artefacto is None:
        log.warning("retencion_model_artifact_unresolvable_fallback_baseline")
        degradado = "artefacto_irresoluble"
        activa = None

    hoy = datetime.now().strftime("%Y-%m-%d")
    desde, hasta = retencion_labels.ventana_vencimientos(months_ahead, hoy=hoy)
    ventana = {"desde": desde, "hasta": hasta}
    adjudicaciones = retencion_labels._cargar_adjudicaciones()
    filas = (
        retencion_labels.vencimientos_con_features(
            adjudicaciones, months_ahead=months_ahead, hoy=hoy
        )
        if activa
        else retencion_labels.vencimientos_proximos(
            adjudicaciones, months_ahead=months_ahead, hoy=hoy
        )
    )
    # El emparejamiento solo hace falta si hay algo que puntuar.
    etiquetas = _etiquetas_retencion(adjudicaciones) if filas else None
    filas, resueltos, excluidos = _separar_resueltos(
        filas, etiquetas, excluir=settings.ML_RETENCION_EXCLUIR_RESUELTOS
    )
    if not filas:
        log.info(
            "retencion_scoring_skip",
            reason="sin_vencimientos",
            horizonte_meses=months_ahead,
            resueltos_detectados=resueltos,
            excluidos=excluidos,
        )
        return {
            "status": "sin_vencimientos",
            "filas": 0,
            "degradado": degradado,
            "purgadas": 0,
            "resueltos_detectados": resueltos,
            "excluidos": excluidos,
            "horizonte_meses": months_ahead,
            "ventana": ventana,
        }

    version: int | None = None
    baseline: _BaselineRetencion | None = None
    niveles: Counter[str] = Counter()
    if activa:
        from services.ml.retencion_model import RetencionModel

        assert artefacto is not None
        probas = RetencionModel.load(artefacto).predict_proba_retencion(filas)
        version = int(activa["version"])
    else:
        log.info("retencion_scoring_baseline", reason="sin_modelo_activo", filas=len(filas))
        baseline = _baseline_retencion(etiquetas)
        probas = []
        for f in filas:
            # La clave tiene que ser la MISMA con la que se agregaron las tasas:
            # ``(normalize_organo(organo), cpv4)``. Hasta 2026-08 se leían
            # ``f.cpv`` y ``f.organo_contratacion`` con ``getattr(..., "")``,
            # dos atributos que ``ParRetencion`` no tiene: los dos salían
            # vacíos y TODAS las filas recibían la media global.
            tasa, nivel = baseline.tasa(normalize_organo(f.organo), f.cpv4)
            niveles[nivel] += 1
            probas.append(min(max(tasa, 0.0), 1.0))

    computed_at = now_utc_iso()
    guardado = PrediccionesRepository().guardar_retencion(
        [
            (f.licitacion_id, f.empresa_id, round(p, 5), round(1 - p, 5), version, computed_at)
            for f, p in zip(filas, probas, strict=True)
        ],
        computed_at=computed_at,
    )
    serving = "modelo" if version is not None else "baseline"
    resultado: dict[str, Any] = {
        "status": "ok" if version is not None else "baseline",
        "filas": len(filas),
        "model_version": version if version is not None else "baseline",
        "serving": serving,
        "degradado": degradado,
        "purgadas": guardado["purgadas"],
        "resueltos_detectados": resueltos,
        "excluidos": excluidos,
        "horizonte_meses": months_ahead,
        "ventana": ventana,
        "tasa_global": baseline.tasa_global if baseline is not None else None,
        "niveles_baseline": dict(niveles) if baseline is not None else None,
        "computed_at": computed_at,
    }
    log.info(
        "retencion_scoring_done" if version is not None else "retencion_baseline_done",
        **{clave: valor for clave, valor in resultado.items() if clave != "status"},
    )
    return resultado


# ── Lectura de la predicción de baja ──────────────────────────────────────


def _baja_real(repo: PrediccionesRepository, licitacion_id: str) -> tuple[float, float] | None:
    """Baja real ``(baja_pct, importe_adjudicado)`` si la licitación fue adjudicada.

    ``importe_adjudicado`` es la suma de todo lo adjudicado en el expediente, y
    el denominador su **presupuesto efectivo**, con la regla del target de
    entrenamiento y de ``calibration.py``: la de
    ``PrediccionesRepository.baja_real_de_expediente``, cuyo docstring cuenta el
    caso que la motivó (una «baja real» del 61% junto a un intervalo entrenado
    contra el 22%). Aquí queda la división, que es dominio; el SQL vivía inline
    en este módulo y bajó a ``db/`` (ADR-022), con lo que el módulo salió del
    ratchet TID251. Gemela de :func:`_baja_real_lote`.
    """
    fila = repo.baja_real_de_expediente(licitacion_id)
    if fila is None:
        return None
    presupuesto = fila.get("presupuesto_efectivo")
    adjudicado = fila.get("total_adjudicado")
    if presupuesto is None or adjudicado is None:
        return None
    presupuesto_efectivo, total_adjudicado = float(presupuesto), float(adjudicado)
    if presupuesto_efectivo <= 0:
        return None
    return (presupuesto_efectivo - total_adjudicado) / presupuesto_efectivo, total_adjudicado


class LoteDesconocidoError(ValueError):
    """El lote pedido no existe o no pertenece a esa licitación.

    Se distingue de ``None`` a propósito: ``None`` es "no hay ni predicción ni
    adjudicación para lo que pediste" y esto es "lo que pediste no existe". Con
    un solo 404 genérico, pedir el lote de otro expediente y pedir un lote que
    aún no se ha scoreado darían el mismo mensaje, y solo uno de los dos es un
    error de quien llama.
    """


def prediccion_baja(licitacion_id: str, lote_id: int | None = None) -> dict[str, Any] | None:
    """Lectura de la predicción materializada y/o la baja real de una licitación.

    - Publicada/abierta: solo estimación del batch (p10/p50/p90).
    - Adjudicada con estimación previa (scoreada antes de adjudicarse): ambas,
      para comparar lo estimado contra lo real.
    - Adjudicada sin estimación previa (adjudicada antes de que corriera el
      batch): solo la baja real.
    - Ninguna de las dos → ``None`` (404).

    Con ``lote_id`` la unidad pasa a ser el lote (S3.1): ver
    :func:`_prediccion_baja_lote`. Sin él la cifra es la agregada de siempre,
    y se le suma ``lotes`` —el desglose por lote— solo cuando el batch por
    lote materializó alguna fila (v140); si no, la respuesta no cambia.

    Raises:
        LoteDesconocidoError: Si ``lote_id`` no pertenece a ``licitacion_id``.
    """
    if lote_id is not None:
        return _prediccion_baja_lote(licitacion_id, lote_id)
    repo = PrediccionesRepository()
    # La fila agregada se pide explícitamente (`lote_numero IS NULL`): desde
    # v140 puede haber además una por lote, y un `fetchone()` sin ese predicado
    # contestaría con el intervalo de un lote cualquiera.
    pred = repo.prediccion_materializada(licitacion_id)
    desglose = repo.predicciones_por_lote(licitacion_id)
    real = _baja_real(repo, licitacion_id)

    if pred is None and real is None and not desglose:
        return None

    data: dict[str, Any] = {"licitacion_id": licitacion_id}
    if pred is not None:
        model_version = pred["model_version"]
        data.update(
            p10=pred["p10"],
            p50=pred["p50"],
            p90=pred["p90"],
            model_version=model_version,
            computed_at=pred["computed_at"],
            serving="modelo" if model_version else "baseline",
        )
    if real is not None:
        baja_real, importe_adjudicado = real
        data["baja_real"] = baja_real
        data["importe_adjudicado"] = importe_adjudicado
    # Aditivo: solo aparece si el batch por lote materializó algo. Sin él la
    # respuesta es byte a byte la de siempre (la ruta serializa con
    # `exclude_unset`).
    if desglose:
        data["lotes"] = [
            {
                "lote_id": fila["lote_id"],
                "lote_numero": str(fila["lote_numero"]),
                "p10": fila["p10"],
                "p50": fila["p50"],
                "p90": fila["p90"],
                "model_version": fila["model_version"],
                "computed_at": fila["computed_at"],
                "serving": "modelo" if fila["model_version"] else "baseline",
            }
            for fila in desglose
        ]
    return data


def _prediccion_baja_lote(licitacion_id: str, lote_id: int) -> dict[str, Any] | None:
    """Predicción y baja real **de un lote** (S3.1).

    Las dos mitades no tienen hoy la misma calidad, y la respuesta lo declara
    en vez de disimularlo:

    - **La baja real sí es del lote.** ``adjudicaciones.lote_id`` existe desde
      v65 y ``lotes.importe`` es el denominador correcto, así que
      ``baja_real``/``importe_adjudicado`` describen exactamente ese lote. Si
      el pliego no publica el importe del lote, no hay denominador y no hay
      baja real: no se sustituye por el del expediente (ADR-014).
    - **La estimación, solo si el batch por lote corrió.** Desde v140
      ``predicciones_baja`` admite una fila por lote, pero el batch solo la
      materializa con ``ML_BAJA_POR_LOTE`` (el switch está condicionado a
      medir antes el ``mae_p50`` por lote). Si existe fila del lote se sirve
      esa; si no, se sirve la del expediente marcada
      ``prediccion_ambito='expediente'``. Es una
      aproximación declarada —la baja es un ratio, no un importe, así que
      aplicar la del expediente a un lote es discutible pero no absurdo—, y
      404 en su lugar dejaría la pantalla del lote sin nada que enseñar
      teniendo un dato que sí existe.

    ``None`` (→ 404) solo cuando el lote no tiene ni estimación ni
    adjudicación, igual que en el camino del expediente.

    Raises:
        LoteDesconocidoError: Si el lote no pertenece a esa licitación.
    """
    repo = PrediccionesRepository()
    lote = repo.lote_de(licitacion_id, lote_id)
    if lote is None:
        raise LoteDesconocidoError(
            f"El lote {lote_id} no pertenece a la licitación {licitacion_id}."
        )

    numero = lote.get("numero")
    ambito = "lote"
    # Por número de lote, no por id: es la clave con la que el batch escribe
    # (v140), y el id cambia en cada re-ingesta.
    pred = repo.prediccion_materializada(licitacion_id, str(numero)) if numero is not None else None
    if pred is None:
        pred = repo.prediccion_materializada(licitacion_id)
        ambito = "expediente"
    real = _baja_real_lote(repo, licitacion_id, lote_id)
    if pred is None and real is None:
        return None

    data: dict[str, Any] = {
        "licitacion_id": licitacion_id,
        "lote_id": lote_id,
        "lote_numero": None if numero is None else str(numero),
    }
    if pred is not None:
        model_version = pred["model_version"]
        data.update(
            p10=pred["p10"],
            p50=pred["p50"],
            p90=pred["p90"],
            model_version=model_version,
            computed_at=pred["computed_at"],
            serving="modelo" if model_version else "baseline",
            prediccion_ambito=ambito,
        )
    if real is not None:
        data["baja_real"], data["importe_adjudicado"] = real
    return data


def _baja_real_lote(
    repo: PrediccionesRepository, licitacion_id: str, lote_id: int
) -> tuple[float, float] | None:
    """``(baja_pct, importe_adjudicado)`` del lote, o ``None``.

    ``None`` cubre los tres casos en los que no hay baja que afirmar: el lote
    no publica importe, nadie lo ha adjudicado todavía, o el importe publicado
    es cero. Ninguno se rellena con el expediente.
    """
    fila = repo.baja_real_de_lote(licitacion_id, lote_id)
    if fila is None:
        return None
    presupuesto = fila.get("presupuesto")
    adjudicado = fila.get("total_adjudicado")
    if presupuesto is None or adjudicado is None:
        return None
    presupuesto, adjudicado = float(presupuesto), float(adjudicado)
    if presupuesto <= 0 or adjudicado <= 0:
        return None
    return (presupuesto - adjudicado) / presupuesto, adjudicado
