"""Drift de los modelos predictivos (Fase 6.3, RFC 20260611-2).

PSI por feature numérica entre la distribución de referencia y la de las filas
de scoring de hoy. Umbrales estándar del proyecto (scheduler.drift_monitor):
<0.10 estable · 0.10-0.25 seguimiento · >0.25 drift significativo → alerta por
el canal existente.

**La referencia no es todo el histórico de entrenamiento, sino su tramo
comparable.** ``construir_dataset_baja`` cubre la serie entera, arranque
incluido, donde los acumuladores de ``services.ml.features`` todavía están
vacíos; ``features_licitaciones_abiertas`` devuelve las abiertas más recientes
(``ORDER BY fecha_publicacion DESC LIMIT``), todas con la ventana de 24 meses
llena. Comparar lo uno con lo otro medía la rampa de arranque del histórico, no
la deriva: daba PSI de 5-6 permanentes en todas las features derivadas de
acumuladores (``n_obs_*``, ``baja_media_*``), y ningún reentrenamiento los iba a
bajar. La referencia se acota al mismo tramo temporal que el scoring
(:func:`_ventana_referencia`).

Además del PSI se vigila el **delta de nulos** por feature. El PSI compara
solo los valores presentes en ambos lados, así que era ciego al caso más grave
posible: una feature disponible al entrenar y ausente al servir. Ver
:data:`_MISSING_DELTA_WARN`.

Dos familias de features no gobiernan la severidad porque su distribución no es
estacionaria por diseño (:data:`_FEATURES_CALENDARIO`,
:data:`_FEATURES_CONTADOR`): se siguen midiendo y se reportan en
``psi_informativo``. Los contadores tienen además su propio control, asimétrico
a propósito: que suban es el sistema funcionando, que se desplomen es el
histórico dejando de acumularse.

**Solo alerta cuando lo que se sirve es el modelo.** El PSI pregunta si las
filas que se puntúan hoy se parecen a las que vio el modelo al entrenar, y esa
pregunta solo tiene destinatario si hay un modelo sirviendo: el baseline no
aprendió de esa distribución, lee la media histórica del segmento, y lo que lo
vigila es la calibración de su intervalo (``services.ml.calibration``). El run
de ``ml-scoring.yml`` del 2026-09-24 servía el baseline en los dos modelos —no
había versión activa— y aun así este monitor mandó, como cada día, un correo
ERROR: "baja_media_organo PSI 5.92 (3 bins sin cobertura), nulos -53% en
duracion_meses". Con ``regimen="baseline"`` se calcula y se devuelve todo
igual, pero va al log a nivel info y no sale correo: el mismo principio que
``calibration._regimen_a_juzgar``, se juzga lo que se sirve hoy.

Lo que ese correo medía, además, no era deriva sino **otra población**. La
mediana de ``n_obs_organo`` era 1.293 en la referencia y 3 en scoring; la de
``n_obs_organo_cpv4``, 243 frente a 0: la mitad de lo abierto hoy es de
órganos con tres adjudicaciones o menos en los 24 meses previos. Un modelo
entrenado sobre lo adjudicado extrapolaría ahí, y por eso la alerta sí importa
cuando se sirve modelo. Y la ventana de referencia arrancaba el 2019-11-15
porque al menos el 5% de las 4.414 «abiertas» era de 2019 o antes: expedientes
zombi, sin adjudicación, que nadie cierra. Esos ya no entran en la población
de scoring (``services.ml.features.corte_abiertas_vivas``).

Una condición que persiste tampoco merece un correo diario: el mismo aviso cada
mañana enseña a no leerlo. La alerta sale con ``dedup_key`` y la ventana de
``observability.alerts.COOLDOWN_MONITOR_DIARIO_S`` (siete días); la clave lleva
la severidad, así que una escalada warn→crit avisa al momento.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger
from services.ml.thresholds import PSI_CRIT, PSI_WARN

if TYPE_CHECKING:
    from services.ml.features import FilaDataset

log = get_logger(__name__)

# Los dos umbrales PSI salen de `services/ml/thresholds.py`, que es de donde los
# lee también `scheduler/drift_monitor.py`. Estaban declarados por duplicado en
# los dos módulos con los mismos valores, que es la forma en que dos vigilantes
# del mismo fenómeno acaban discrepando: el día que alguien afine uno, el otro
# sigue avisando con el criterio viejo y nadie sabe cuál manda.
_PSI_WARN = PSI_WARN
_PSI_CRIT = PSI_CRIT

# Diferencia admisible entre la tasa de nulos de una feature en entrenamiento y
# en scoring. El PSI solo compara los valores **presentes**, así que una feature
# que existe al entrenar y no al servir le resultaba invisible: ``n_ofertas``
# venía de ``adjudicaciones`` (dato post-adjudicación), era NaN en el 100% de
# las filas de scoring, y el monitor reportaba PSI 0.00 "estable" mientras el
# modelo se partía sobre ella. Esa asimetría es un fallo de diseño de features,
# no una deriva de datos, y es la que este umbral vigila. Se mira en valor
# absoluto: el sentido contrario --presente al servir, NaN en media serie de
# entrenamiento-- manda producción por una rama del GBM que se ajustó sobre
# otra subpoblación.
_MISSING_DELTA_WARN = 0.20
_MISSING_DELTA_CRIT = 0.50

# Cuantil de las anclas de scoring que fija el inicio de la ventana de
# referencia. No se usa el mínimo: basta una licitación abierta publicada hace
# años para que la ventana vuelva a ser el histórico entero, y con ella el
# falso positivo permanente. El cuantil solo no bastó: el 2026-09-24 los
# zombis de 2019 o antes pasaban del 5% de las abiertas y la ventana arrancaba
# el 2019-11-15. Desde entonces la población de scoring los deja fuera en origen
# (``services.ml.features.corte_abiertas_vivas``), y el cuantil queda para lo
# que ese corte no ve: una abierta con el plazo de ofertas reciente pero
# publicada hace años, que se ancla en su publicación.
_CUANTIL_VENTANA = 0.05

# Por debajo de estas filas la ventana no da una referencia utilizable y se
# vuelve al histórico completo, dejándolo dicho en el resultado
# (``ventana_ref``) en vez de comparar contra un puñado de filas.
_MIN_REF_VENTANA = 200

# Calendario: el scoring es una foto de las abiertas de ahora y nunca cubre los
# doce meses como los cubre un histórico de años. El PSI de ``mes`` mide qué
# meses hay abiertos, no deriva.
_FEATURES_CALENDARIO = frozenset({"mes", "trimestre"})

# Contadores: crecen con la densidad del histórico acumulado, así que su PSI
# contra cualquier referencia anterior es alto por construcción. Que suban es el
# sistema funcionando; que **bajen** sí es un fallo real --la ingesta dejó de
# acumular, o el dedupe se llevó medio histórico-- y eso lo vigila
# ``_CONTADOR_CAIDA_*`` sobre la mediana, que sí tiene sentido comparar.
_FEATURES_CONTADOR = frozenset({"n_obs_organo", "n_obs_cpv4", "n_obs_organo_cpv4"})

# Mediana del contador en scoring como fracción de la de referencia.
_CONTADOR_CAIDA_WARN = 0.50
_CONTADOR_CAIDA_CRIT = 0.25


def _numeric_features() -> tuple[str, ...]:
    """Columnas numéricas del dataset, derivadas del orden canónico.

    Se calcula desde ``FEATURE_COLUMNS`` en vez de mantener una lista paralela:
    una feature nueva entra en el monitor sola, sin que nadie tenga que
    acordarse de añadirla aquí.
    """
    from services.ml.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS

    return FEATURE_COLUMNS[len(CATEGORICAL_COLUMNS) :]


@dataclass(frozen=True)
class _Psi:
    """PSI y la resolución con la que se pudo medir."""

    valor: float
    # Bins con masa en la referencia. Con 1 o 0 la referencia no distingue nada
    # y el PSI no significa "estable", significa "no estoy midiendo".
    bins_ref: int
    # Bins con masa en referencia y ninguna en scoring: es lo que de verdad
    # infla el PSI, y decirlo hace legible un número que solo no lo es.
    vacios: int


def _cortes(ref_ordenada: list[float], n_bins: int) -> list[float]:
    """Cortes por cuantiles de la referencia, **sin repetidos**.

    Con empates masivos (``n_lotes`` es 0 en la mayoría de expedientes) los
    cortes por cuantiles salen todos iguales, el histograma colapsa a un solo
    bin, los dos lados quedan idénticos y el PSI da 0.0000 exacto. Ese cero se
    leía como "estable" cuando lo que decía era "no distingo nada" --el mismo
    error de fondo que el delta de nulos vino a corregir--. Deduplicar deja los
    bins que la referencia realmente separa, y ``_Psi.bins_ref`` los publica.
    """
    cortes: list[float] = []
    for i in range(1, n_bins):
        corte = ref_ordenada[int(len(ref_ordenada) * i / n_bins)]
        if not cortes or corte > cortes[-1]:
            cortes.append(corte)
    return cortes


def _psi_detalle(ref: list[float], cur: list[float], n_bins: int = 10) -> _Psi:
    """PSI entre dos muestras, con bins por cuantiles de la referencia."""
    if len(ref) < 20 or len(cur) < 20:
        return _Psi(0.0, 0, 0)
    cortes = _cortes(sorted(ref), n_bins)

    def _hist(valores: list[float]) -> list[float]:
        conteos = [0] * (len(cortes) + 1)
        for v in valores:
            b = 0
            while b < len(cortes) and v >= cortes[b]:
                b += 1
            conteos[b] += 1
        total = len(valores)
        return [c / total for c in conteos]

    h_ref, h_cur = _hist(ref), _hist(cur)
    # eps = la proporción más pequeña que la muestra puede resolver, en vez de
    # un 1e-6 fijo. Con el fijo, cada bin vacío sumaba +1.15 al PSI pasara lo
    # que pasara: un "PSI 6.43" no era "veinticinco veces el umbral", era "hay
    # cinco bins vacíos", y el número no se podía leer ni comparar entre
    # corridas.
    eps = 1.0 / max(len(ref), len(cur))
    valor = sum(
        (pc - pr) * math.log((pc + eps) / (pr + eps)) for pr, pc in zip(h_ref, h_cur, strict=True)
    )
    return _Psi(
        valor=valor,
        bins_ref=sum(1 for p in h_ref if p > 0),
        vacios=sum(1 for pr, pc in zip(h_ref, h_cur, strict=True) if pr > 0 and pc == 0.0),
    )


def _psi(ref: list[float], cur: list[float], n_bins: int = 10) -> float:
    return _psi_detalle(ref, cur, n_bins).valor


def _mediana(valores: list[float]) -> float | None:
    if not valores:
        return None
    ordenada = sorted(valores)
    medio = len(ordenada) // 2
    if len(ordenada) % 2:
        return ordenada[medio]
    return (ordenada[medio - 1] + ordenada[medio]) / 2.0


def _caida_contador(ref: list[float], cur: list[float]) -> dict[str, float | None]:
    """Mediana del contador en los dos lados y su cociente.

    Un cociente < 1 dice que las filas que se están puntuando se apoyan en menos
    histórico del que vio el modelo. Es la única dirección en la que un contador
    puede ir mal, y la mitad del PSI que en estas features sí importa.
    """
    med_ref, med_cur = _mediana(ref), _mediana(cur)
    ratio = med_cur / med_ref if med_ref and med_ref > 0 and med_cur is not None else None
    return {
        "mediana_ref": med_ref,
        "mediana_scoring": med_cur,
        "ratio": round(ratio, 4) if ratio is not None else None,
    }


def _ventana_referencia(
    entrenamiento: list[Any], scoring: list[Any]
) -> tuple[list[Any], str | None]:
    """Tramo del entrenamiento comparable con el scoring.

    Devuelve ``(filas, corte)``; ``corte`` es ``None`` cuando la ventana deja
    menos de :data:`_MIN_REF_VENTANA` filas y se cae al histórico completo. El
    resultado lo publica en ``ventana_ref`` para que la alerta diga contra qué
    se comparó: un PSI alto contra el histórico entero y uno contra el tramo
    reciente no significan lo mismo.
    """
    fechas = sorted(f.fecha for f in scoring)
    corte = fechas[min(int(len(fechas) * _CUANTIL_VENTANA), len(fechas) - 1)]
    recientes = [f for f in entrenamiento if f.fecha >= corte]
    if len(recientes) < _MIN_REF_VENTANA:
        return entrenamiento, None
    return recientes, corte


def _resolver_regimen(regimen: str | None) -> str | None:
    """Lo que se está sirviendo: lo que diga el llamador o, si no lo sabe, la tabla.

    El job nocturno lo pasa (el ``serving`` del batch que acaba de escribir).
    Un llamador que no lo sabe lo resuelve con ``regimen_servido()``, la misma
    fuente que usa la calibración. Si esa lectura falla devuelve ``None`` y se
    alerta como siempre (fail-open): callar el monitor porque no se pudo
    averiguar qué se sirve sería perder la alerta por un fallo ajeno a ella.
    """
    if regimen is not None:
        return regimen
    try:
        from db.repositories.ml_dataset import MlDatasetRepository

        return MlDatasetRepository().regimen_servido()
    except Exception as exc:
        log.warning("ml_drift_regimen_no_resuelto", error=str(exc))
        return None


def comprobar_drift_baja(
    *, scoring: list[FilaDataset] | None = None, regimen: str | None = None
) -> dict[str, Any]:
    """PSI de las features de scoring de hoy vs el tramo comparable del dataset.

    ``scoring`` son las filas que el batch acaba de puntuar
    (:func:`~services.ml.features.features_licitaciones_abiertas`). El job
    nocturno las pasa para no construirlas dos veces —cada construcción carga
    el histórico entero, ~1 min—; sin ellas se construyen aquí.

    ``regimen`` es lo que se está sirviendo (``"modelo"``/``"baseline"``, el
    ``serving`` del batch) y decide si una deriva alerta (ver la cabecera del
    módulo). Sin él se resuelve con :func:`_resolver_regimen`.

    El resultado lleva ``regimen_servido`` y ``alerta``: ``"no_aplica"`` (nada
    que avisar), ``"suprimida_regimen"`` (hay deriva, pero lo servido es el
    baseline), lo que devolvió ``notify`` (``"enviada"``,
    ``"suprimida_cooldown"`` o ``"suprimida_nivel"``) o ``"fallida"`` si el
    canal lanzó.

    Fail-open: cualquier error se loguea y devuelve estado desconocido (el
    scoring no se bloquea por el monitor).
    """
    regimen_servido = regimen
    try:
        from services.ml.features import construir_dataset_baja, features_licitaciones_abiertas

        if scoring is None:
            scoring = features_licitaciones_abiertas()
        regimen_servido = _resolver_regimen(regimen)
        sin_datos: dict[str, Any] = {
            "status": "sin_datos",
            "regimen_servido": regimen_servido,
            "alerta": "no_aplica",
        }
        # Sin abiertas ni se construye el dataset de entrenamiento: es lo más
        # caro del monitor y no habría nada con qué compararlo.
        if not scoring:
            return sin_datos
        entrenamiento, _ = construir_dataset_baja()
        if not entrenamiento:
            return sin_datos

        referencia, corte = _ventana_referencia(entrenamiento, scoring)

        psi_por_feature: dict[str, float] = {}
        psi_informativo: dict[str, float] = {}
        bins_vacios: dict[str, int] = {}
        missing_por_feature: dict[str, float] = {}
        sin_resolucion: list[str] = []
        contadores: dict[str, dict[str, float | None]] = {}

        for col in _numeric_features():
            ref = [float(f.features[col]) for f in referencia if f.features.get(col) is not None]
            cur = [float(f.features[col]) for f in scoring if f.features.get(col) is not None]
            detalle = _psi_detalle(ref, cur)
            estacionaria = col not in _FEATURES_CALENDARIO and col not in _FEATURES_CONTADOR
            destino = psi_por_feature if estacionaria else psi_informativo
            destino[col] = round(detalle.valor, 4)
            bins_vacios[col] = detalle.vacios
            if detalle.bins_ref <= 1:
                sin_resolucion.append(col)
            # Delta de nulos: positivo = falta más al servir que al entrenar.
            missing_ref = 1.0 - len(ref) / len(referencia)
            missing_cur = 1.0 - len(cur) / len(scoring)
            missing_por_feature[col] = round(missing_cur - missing_ref, 4)
            if col in _FEATURES_CONTADOR:
                contadores[col] = _caida_contador(ref, cur)

        peor_col, peor = max(psi_por_feature.items(), key=lambda kv: kv[1], default=("", 0.0))
        peor_missing_col, peor_missing = max(
            missing_por_feature.items(), key=lambda kv: abs(kv[1]), default=("", 0.0)
        )
        peor_missing_abs = abs(peor_missing)
        ratios = [c["ratio"] for c in contadores.values() if c["ratio"] is not None]
        peor_ratio = min(ratios) if ratios else None

        if (
            peor >= _PSI_CRIT
            or peor_missing_abs >= _MISSING_DELTA_CRIT
            or (peor_ratio is not None and peor_ratio < _CONTADOR_CAIDA_CRIT)
        ):
            severity = "crit"
        elif (
            peor >= _PSI_WARN
            or peor_missing_abs >= _MISSING_DELTA_WARN
            or (peor_ratio is not None and peor_ratio < _CONTADOR_CAIDA_WARN)
        ):
            severity = "warn"
        else:
            severity = "ok"

        ventana = corte or "histórico completo"
        alerta = "no_aplica"
        if severity != "ok":
            contexto: dict[str, Any] = {
                "severity": severity,
                "regimen_servido": regimen_servido,
                "ventana_ref": ventana,
                "n_ref": len(referencia),
                "n_scoring": len(scoring),
                "psi": psi_por_feature,
                "psi_informativo": psi_informativo,
                "bins_vacios": bins_vacios,
                "missing_delta": missing_por_feature,
                "contadores": contadores,
                "sin_resolucion": sin_resolucion,
            }
            if regimen_servido == "baseline":
                # Se mide y se deja dicho, pero no despierta a nadie: no hay
                # modelo al que esta deriva pueda estar descolocando.
                log.info("ml_drift_detected_no_servido", **contexto)
                alerta = "suprimida_regimen"
            else:
                log.warning("ml_drift_detected", **contexto)
                try:
                    from observability.alerts import COOLDOWN_MONITOR_DIARIO_S, notify

                    alerta = notify(
                        "warn" if severity == "warn" else "error",
                        f"Drift en features del modelo de baja: "
                        f"{peor_col or 'n/a'} PSI {peor:.2f} "
                        f"({bins_vacios.get(peor_col, 0)} bins sin cobertura), "
                        f"nulos {peor_missing:+.0%} en {peor_missing_col or 'n/a'}",
                        f"referencia={ventana} (n={len(referencia)}) scoring n={len(scoring)} "
                        f"regimen_servido={regimen_servido} "
                        f"psi={psi_por_feature} informativo={psi_informativo} "
                        f"missing_delta={missing_por_feature} contadores={contadores} "
                        f"sin_resolucion={sin_resolucion}",
                        # Clave por severidad: la deriva de ayer calla durante
                        # la ventana; una escalada warn→crit cambia de clave y
                        # sale al momento.
                        dedup_key=f"ml_drift_baja:{severity}",
                        cooldown_s=COOLDOWN_MONITOR_DIARIO_S,
                    )
                except Exception:  # canal de alertas opcional
                    log.debug("ml_drift_alert_channel_unavailable")
                    alerta = "fallida"
        return {
            "status": severity,
            "psi": psi_por_feature,
            "psi_max": peor,
            "psi_peor_feature": peor_col,
            "psi_informativo": psi_informativo,
            "bins_vacios": bins_vacios,
            "sin_resolucion": sin_resolucion,
            "missing_delta": missing_por_feature,
            "missing_delta_max": peor_missing_abs,
            "contadores": contadores,
            "ventana_ref": corte,
            "n_ref": len(referencia),
            "n_scoring": len(scoring),
            "regimen_servido": regimen_servido,
            "alerta": alerta,
        }
    except Exception as e:
        log.warning("ml_drift_check_failed", error=str(e))
        return {
            "status": "error",
            "error": str(e),
            "regimen_servido": regimen_servido,
            "alerta": "no_aplica",
        }
