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
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

_PSI_WARN = 0.10
_PSI_CRIT = 0.25

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
# años --las hay, nadie las cierra formalmente-- para que la ventana vuelva a
# ser el histórico entero, y con ella el falso positivo permanente.
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


def comprobar_drift_baja() -> dict[str, Any]:
    """PSI de las features de scoring de hoy vs el tramo comparable del dataset.

    Fail-open: cualquier error se loguea y devuelve estado desconocido (el
    scoring no se bloquea por el monitor).
    """
    try:
        from services.ml.features import construir_dataset_baja, features_licitaciones_abiertas

        entrenamiento, _ = construir_dataset_baja()
        scoring = features_licitaciones_abiertas()
        if not entrenamiento or not scoring:
            return {"status": "sin_datos"}

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
        if severity != "ok":
            log.warning(
                "ml_drift_detected",
                severity=severity,
                ventana_ref=ventana,
                n_ref=len(referencia),
                n_scoring=len(scoring),
                psi=psi_por_feature,
                psi_informativo=psi_informativo,
                bins_vacios=bins_vacios,
                missing_delta=missing_por_feature,
                contadores=contadores,
                sin_resolucion=sin_resolucion,
            )
            try:
                from observability.alerts import notify

                notify(
                    "warn" if severity == "warn" else "error",
                    f"Drift en features del modelo de baja: "
                    f"{peor_col or 'n/a'} PSI {peor:.2f} "
                    f"({bins_vacios.get(peor_col, 0)} bins sin cobertura), "
                    f"nulos {peor_missing:+.0%} en {peor_missing_col or 'n/a'}",
                    f"referencia={ventana} (n={len(referencia)}) scoring n={len(scoring)} "
                    f"psi={psi_por_feature} informativo={psi_informativo} "
                    f"missing_delta={missing_por_feature} contadores={contadores} "
                    f"sin_resolucion={sin_resolucion}",
                )
            except Exception:  # canal de alertas opcional
                log.debug("ml_drift_alert_channel_unavailable")
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
        }
    except Exception as e:
        log.warning("ml_drift_check_failed", error=str(e))
        return {"status": "error", "error": str(e)}
