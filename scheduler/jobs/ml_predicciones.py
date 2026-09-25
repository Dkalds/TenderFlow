"""Jobs de modelos predictivos (Fase 6, RFC 20260611-2).

- ``run_scoring``: batch diario que materializa ``predicciones_baja`` para
  licitaciones abiertas (serving = lectura de tabla, patrón ``ml_proba``),
  pasa los monitores de drift y calibración y **purga** las predicciones que
  ya nadie va a refrescar: expedientes cerrados hace tiempo y abiertas muertas
  sin adjudicar.
- ``run_retrain``: re-entrenamiento mensual; registra la versión nueva en
  ``model_versions`` SIN activar (salvo ``ML_PRED_AUTO_ACTIVATE`` y criterios
  del RFC cumplidos). La activación es decisión humana vía model_registry.

:func:`main` es el CLI que ejecutan ``.github/workflows/ml-scoring.yml`` y
``train-predictivos.yml``; sus subcomandos están descritos en la sección CLI.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger

if TYPE_CHECKING:
    from db.repositories.predicciones import PrediccionesRepository

log = get_logger(__name__)

# Cuánto sobrevive la predicción de un expediente ya cerrado. El upsert nunca
# purga y `services/analytics/scoring_signals.py` carga la tabla ENTERA a un
# dict en cada refresco de caché, así que su crecimiento monótono es coste de
# memoria del camino caliente, no solo de disco.
DIAS_RETENCION_PREDICCIONES = 90


def purgar_predicciones_cerradas(dias: int = DIAS_RETENCION_PREDICCIONES) -> dict[str, Any]:
    """Borra predicciones de expedientes cerrados hace más de ``dias`` días.

    90 días es el margen entre "el expediente se cerró" y "ya nadie va a mirar
    la estimación que le dimos": el modo page-aligned del Detalle sigue
    puntuando expedientes cerrados recientes, y quitarles el margen el mismo
    día del cierre les cambiaría el score sin avisar.

    Fail-open, como el resto del batch: un fallo de la purga se loguea y no
    tumba el scoring — no haber borrado filas viejas nunca es peor que no
    publicar predicciones nuevas.
    """
    from db.repositories.predicciones import PrediccionesRepository

    corte = (datetime.now(UTC) - timedelta(days=dias)).strftime("%Y-%m-%d")
    try:
        borradas = PrediccionesRepository().purgar_cerradas(antes_de=corte)
    except Exception as exc:
        log.warning("ml_predicciones_purga_failed", error=str(exc), corte=corte)
        return {"status": "error", "borradas": 0, "corte": corte, "error": str(exc)}
    log.info("ml_predicciones_purgadas", borradas=borradas, corte=corte, dias=dias)
    return {"status": "ok", "borradas": borradas, "corte": corte}


def purgar_predicciones_sin_adjudicar(corte: str | None = None) -> dict[str, Any]:
    """Borra predicciones de licitaciones muertas sin adjudicar.

    Complementa a :func:`purgar_predicciones_cerradas`, que solo ve estados
    terminales: una licitación que nunca se adjudicó ni se cerró sale de la
    población del batch al superar ``MESES_MAX_SIN_ADJUDICAR`` y su fila se
    quedaba para siempre con la cifra de la última noche en que contó como
    abierta (el criterio exacto está en
    :meth:`PrediccionesRepository.purgar_sin_adjudicar`).

    ``corte`` tiene que ser el de la población
    (:func:`services.ml.features.corte_abiertas_vivas`), y ``run_scoring`` lo
    fija al empezar. Calculado aquí, al final, una corrida que cruzara la
    medianoche purgaría con el corte del día siguiente filas que acaba de
    escribir, y el verify exacto —que cuenta las filas de la corrida— fallaría
    sin avería real. Sin ``corte`` (uso suelto) se calcula en el momento.

    Fail-open, como :func:`purgar_predicciones_cerradas`.
    """
    from db.repositories.predicciones import PrediccionesRepository
    from services.ml.features import corte_abiertas_vivas

    corte = corte or corte_abiertas_vivas()
    try:
        borradas = PrediccionesRepository().purgar_sin_adjudicar(antes_de=corte)
    except Exception as exc:
        log.warning("ml_predicciones_purga_sin_adjudicar_failed", error=str(exc), corte=corte)
        return {"status": "error", "borradas": 0, "corte": corte, "error": str(exc)}
    log.info("ml_predicciones_purgadas_sin_adjudicar", borradas=borradas, corte=corte)
    return {"status": "ok", "borradas": borradas, "corte": corte}


@contextmanager
def _cronometrar(duraciones: dict[str, float], fase: str) -> Iterator[None]:
    """Anota en ``duraciones`` los segundos (1 decimal) que tarda el bloque.

    Se anota y se loguea también si el bloque lanza, y al cerrar cada fase, no
    solo en el resumen final: si el job muere por ``timeout-minutes`` no llega
    a haber resumen, y la última fase logueada dice dónde se fue el tiempo.
    """
    inicio = time.monotonic()
    try:
        yield
    finally:
        duraciones[fase] = round(time.monotonic() - inicio, 1)
        log.info("ml_scoring_fase", fase=fase, duracion_s=duraciones[fase])


def run_scoring() -> dict[str, Any]:
    """Batch diario: baja, baja por lote, retención, monitores y purgas.

    Las features de las licitaciones abiertas se construyen **una vez** y las
    comparten el batch de baja y el monitor de drift. El drift las recalculaba
    por su cuenta —otra carga del histórico entero— y el 2026-09-24 tardó
    ~1 min 55 s de los 1.049 s del job, con ``timeout-minutes: 20``.

    Cada fase se cronometra en ``duraciones_s`` (más ``total``) para ver venir
    el siguiente acercamiento al timeout en el resumen del job, antes de que
    lo toque. ``baja`` incluye construir las features.
    """
    from services.ml.calibration import comprobar_calibracion_baja
    from services.ml.drift import comprobar_drift_baja
    from services.ml.features import corte_abiertas_vivas, features_licitaciones_abiertas
    from services.ml.scoring import score_predicciones_baja, score_predicciones_retencion

    inicio = time.monotonic()
    duraciones: dict[str, float] = {}
    # Mismo instante que la población que se va a puntuar; ver por qué en
    # purgar_predicciones_sin_adjudicar.
    corte_vivas = corte_abiertas_vivas()

    with _cronometrar(duraciones, "baja"):
        filas = features_licitaciones_abiertas()
        baja = score_predicciones_baja(filas=filas)
    with _cronometrar(duraciones, "baja_por_lote"):
        baja_por_lote = _score_baja_por_lote_si_activo()
    with _cronometrar(duraciones, "retencion"):
        retencion = score_predicciones_retencion()
    with _cronometrar(duraciones, "drift"):
        # El régimen es el que acaba de servir ESTA corrida (``serving`` del
        # batch de baja), no el que dejó la anterior en la tabla. Con
        # ``sin_abiertas`` no hay régimen: ``None``.
        drift = comprobar_drift_baja(scoring=filas, regimen=baja.get("serving"))
    with _cronometrar(duraciones, "calibracion"):
        calibracion = comprobar_calibracion_baja()
    # Después de escribir, nunca antes: si el batch se cae a mitad, lo último
    # que conviene es haber borrado ya filas que iba a refrescar.
    with _cronometrar(duraciones, "purga"):
        purga = {
            "cerradas": purgar_predicciones_cerradas(),
            "sin_adjudicar": purgar_predicciones_sin_adjudicar(corte_vivas),
        }
    duraciones["total"] = round(time.monotonic() - inicio, 1)
    return {
        "baja": baja,
        "baja_por_lote": baja_por_lote,
        "retencion": retencion,
        "drift": drift,
        "calibracion": calibracion,
        "purga": purga,
        "duraciones_s": duraciones,
    }


def _score_baja_por_lote_si_activo() -> dict[str, Any]:
    """Batch por lote (v140), solo con ``ML_BAJA_POR_LOTE`` encendido.

    Apagado por defecto: sustituir la granularidad servida está condicionado a
    que ``scripts/comparar_baja_por_lote.py`` mida una mejora de ``mae_p50``.
    Encendido, un fallo aquí no tumba el batch agregado —que ya escribió y es
    lo que se sirve—: se loguea y se devuelve como ``error``.
    """
    from config import settings

    if not bool(getattr(settings, "ML_BAJA_POR_LOTE", False)):
        return {"status": "desactivado"}
    from services.ml.scoring import score_predicciones_baja_por_lote

    try:
        return score_predicciones_baja_por_lote()
    except Exception as exc:
        log.warning("ml_scoring_por_lote_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}


def run_retrain() -> dict[str, Any]:
    from services.ml.baja_model import entrenar as entrenar_baja
    from services.ml.retencion_model import entrenar as entrenar_retencion

    resultados = {"baja": entrenar_baja(), "retencion": entrenar_retencion()}
    for nombre, resumen in resultados.items():
        if resumen.get("status") == "ok" and not resumen.get("activado"):
            log.info(
                "ml_retrain_pending_activation",
                modelo=nombre,
                version=resumen.get("version"),
                cumple_criterios=resumen.get("cumple_criterios"),
            )
    return resultados


# ── CLI ───────────────────────────────────────────────────────────────────────
#
# `python -m scheduler.jobs.ml_predicciones <subcomando>`, invocado por
# .github/workflows/{ml-scoring,train-predictivos}.yml. La lógica vive aquí y
# no en un heredoc del YAML para que pase por ruff/mypy/tests como el resto del
# código. Contrato con los workflows:
#
# - `debe-correr` (ml-scoring.yml, guard): lee `ML_SCORING_FORZAR` y escribe
#   `correr=true|false` y `motivo=<...>` en $GITHUB_OUTPUT. Sale con 0.
# - `scoring` (subcomando por defecto): el batch. Escribe `baja_computed_at` y
#   `baja_filas` en $GITHUB_OUTPUT y el resumen de la corrida en
#   $GITHUB_STEP_SUMMARY. Sale con 1 si baja falla o el serving se degradó.
# - `verify`: lee `ML_VERIFY_COMPUTED_AT` y `ML_VERIFY_FILAS` (los outputs de
#   `scoring`) y comprueba que esas filas están en la BD.
# - `retrain` (train-predictivos.yml): escribe `artefactos` en $GITHUB_OUTPUT.
#
# Todos cierran el pool Postgres al salir (`main`).

_USO = "python -m scheduler.jobs.ml_predicciones [scoring|verify|retrain|debe-correr]"

# Estados de `score_predicciones_baja` que NO son fallo: "sin_abiertas" es el
# caso legítimo de no haber licitaciones abiertas que puntuar.
_SCORING_OK_STATUSES = frozenset({"ok", "sin_abiertas"})

# Estados de `entrenar()` que NO son fallo: sin histórico suficiente el modelo
# no se entrena y se sigue sirviendo el baseline (criterio de honestidad del
# RFC 20260611-2), que es distinto de que el entrenamiento reviente.
_RETRAIN_OK_STATUSES = frozenset({"ok", "datos_insuficientes"})

# Edad máxima tolerada de `predicciones_baja` en el verify SIN los outputs del
# scoring (uso manual, plano local, o un step de scoring que no pudo escribir
# $GITHUB_OUTPUT). Con cron diario, 26 h cubrían la corrida anterior más el
# desfase típico del scheduler de Actions. Por encima las filas son de una
# corrida que ya no existe: el upsert nunca purga, así que sin este control una
# tabla poblada hace semanas pasaba la verificación como si el batch hubiera
# escrito. En Actions manda la comprobación exacta por `computed_at`.
_MAX_EDAD_PREDICCIONES_HORAS = 26.0


def _a_utc(instante: datetime) -> datetime:
    """``instante`` en UTC; sin zona horaria se interpreta como UTC, no local."""
    if instante.tzinfo is None:
        return instante.replace(tzinfo=UTC)
    return instante.astimezone(UTC)


def _instante_utc(valor: object) -> datetime | None:
    """``valor`` (ISO-8601 o ``datetime``) como instante UTC, o ``None``.

    ``computed_at`` es TEXT en el esquema (lo escribe ``now_utc_iso()``), pero
    se acepta ``datetime`` por si algún backend lo devuelve ya tipado.
    """
    if isinstance(valor, datetime):
        return _a_utc(valor)
    if isinstance(valor, str) and valor:
        try:
            return _a_utc(datetime.fromisoformat(valor.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _edad_horas(valor: object) -> float | None:
    """Horas transcurridas desde ``valor`` (formatos de :func:`_instante_utc`)."""
    instante = _instante_utc(valor)
    if instante is None:
        return None
    return (datetime.now(UTC) - instante).total_seconds() / 3600.0


def _escribir_github_output(valores: dict[str, str]) -> None:
    """Añade ``clave=valor`` a ``$GITHUB_OUTPUT``; fuera de Actions no hace nada.

    Una línea por clave: un salto dentro del valor rompería el parseo del
    fichero (los multilínea necesitan heredoc), así que se aplana. Los errores
    de escritura se propagan y cada llamador decide si son fatales.
    """
    destino = os.environ.get("GITHUB_OUTPUT")
    if not destino:
        return
    lineas = [f"{clave}={' '.join(valor.splitlines())}\n" for clave, valor in valores.items()]
    with open(destino, "a", encoding="utf-8") as fh:
        fh.write("".join(lineas))


def _escribir_step_summary(markdown: str) -> None:
    """Añade ``markdown`` al resumen del job; fuera de Actions no hace nada."""
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if not destino:
        return
    with open(destino, "a", encoding="utf-8") as fh:
        fh.write(markdown if markdown.endswith("\n") else markdown + "\n")


# ── Guard: una corrida al día ─────────────────────────────────────────────────


def debe_correr(ultimo_computed_at: object, ahora: datetime, *, forzar: bool) -> tuple[bool, str]:
    """¿Toca puntuar? Una corrida por día UTC, dispare lo que dispare el workflow.

    ``ml-scoring.yml`` se encadena a cada ``scrape-daily`` (seis al día) más un
    cron de respaldo, así que sin guard puntuaría seis veces al día. Tampoco
    vale decidirlo por la hora de arranque: el cron fijo de antes
    (``30 7 * * *``) arrancó en 30 corridas entre las 08:05 y las 19:29 UTC. Se
    decide por la fecha UTC del último ``computed_at``.

    Ante la duda, corre: un ``computed_at`` ilegible o de un día futuro no
    demuestra que hoy ya se puntuó, y saltarse días en silencio es peor que
    puntuar dos veces (el upsert es idempotente). Con el futuro, además, saltar
    no se corregiría solo: una sola fila con fecha futura fija el ``MAX`` y el
    guard saltaría todos los días hasta alcanzarla.

    Args:
        ultimo_computed_at: ``MAX(computed_at)`` de ``predicciones_baja``
            (ISO-8601 o ``datetime``; sin zona = UTC), ``None`` si está vacía.
        ahora: Instante de referencia (sin zona = UTC).
        forzar: Dispatch manual: corre siempre.

    Returns:
        ``(correr, motivo)``; ``motivo`` es uno de ``forzado``,
        ``sin_scoring_previo``, ``ultimo_scoring_ilegible``,
        ``primera_del_dia``, ``ultimo_scoring_futuro`` o ``ya_puntuado_hoy``
        (el único que no corre).
    """
    if forzar:
        return True, "forzado"
    if ultimo_computed_at is None or ultimo_computed_at == "":
        return True, "sin_scoring_previo"
    ultimo = _instante_utc(ultimo_computed_at)
    if ultimo is None:
        return True, "ultimo_scoring_ilegible"
    dia_ultimo, hoy = ultimo.date(), _a_utc(ahora).date()
    if dia_ultimo < hoy:
        return True, "primera_del_dia"
    if dia_ultimo > hoy:
        return True, "ultimo_scoring_futuro"
    return False, "ya_puntuado_hoy"


def debe_correr_cli() -> int:
    """Guard del workflow: escribe ``correr``/``motivo`` en ``$GITHUB_OUTPUT``.

    ``ML_SCORING_FORZAR=true`` (sin distinguir mayúsculas; el YAML pasa el
    literal de ``github.event_name == 'workflow_dispatch'``) corre sin consultar
    la BD.

    Fail-open: si no puede leer la BD deja pasar (``lectura_fallida``) y los
    steps reales harán visible el error, en vez de saltarse el día en silencio.
    Lo único que lo pone en rojo es no poder escribir el output: sin ``correr``
    el YAML salta todos los steps y el día se perdería con el job en verde.

    El ``computed_at`` es el ``MAX`` de toda la tabla, filas por lote incluidas.
    Vale igual: el job las escribe en la misma corrida que las agregadas. Una
    pasada manual de ``scripts/score_predicciones.py`` sí cuenta como scoring
    del día; si ese día hacen falta los monitores y las purgas, el dispatch
    manual fuerza la corrida.
    """
    forzar = os.environ.get("ML_SCORING_FORZAR", "").strip().lower() == "true"
    ultimo: object = None
    correr, motivo = True, "lectura_fallida"
    try:
        if not forzar:
            from db.repositories.predicciones import PrediccionesRepository

            ultimo = PrediccionesRepository().estado("predicciones_baja")["ultimo_computed_at"]
    except Exception as exc:
        log.warning("ml_scoring_guard_lectura_failed", error=str(exc))
    else:
        correr, motivo = debe_correr(ultimo, datetime.now(UTC), forzar=forzar)

    log.info(
        "ml_scoring_guard",
        correr=correr,
        motivo=motivo,
        forzar=forzar,
        ultimo_computed_at=ultimo,
    )
    try:
        _escribir_github_output({"correr": "true" if correr else "false", "motivo": motivo})
    except OSError as exc:
        log.error("ml_scoring_guard_output_failed", error=str(exc), correr=correr)
        return 1
    return 0


# ── Scoring: outputs y resumen del job ────────────────────────────────────────


def _salidas_scoring(baja: dict[str, Any]) -> dict[str, str]:
    """Outputs del step de scoring que consume ``verify``.

    - ``ok``: el ``computed_at`` de la corrida y las filas agregadas escritas.
    - ``sin_abiertas``: ``computed_at`` vacío y ``0``, el único caso en que
      verify acepta no encontrar nada.
    - cualquier otro (fallo, o un ``ok`` sin ``computed_at``): los dos vacíos.
      Nunca ``0``: verify lo leería como ``sin_abiertas`` y daría por buena una
      corrida que no escribió.
    """
    status = baja.get("status")
    computed_at = baja.get("computed_at")
    if status == "ok" and isinstance(computed_at, str) and computed_at:
        return {"baja_computed_at": computed_at, "baja_filas": str(int(baja.get("filas") or 0))}
    if status == "sin_abiertas":
        return {"baja_computed_at": "", "baja_filas": "0"}
    return {"baja_computed_at": "", "baja_filas": ""}


# Filas del resumen del job, en el orden en que corren las fases.
_FASES_RESUMEN: tuple[tuple[str, str], ...] = (
    ("baja", "Baja (agregada)"),
    ("baja_por_lote", "Baja por lote"),
    ("retencion", "Retención"),
    ("drift", "Drift"),
    ("calibracion", "Calibración"),
    ("purga", "Purgas"),
)

# Cifras de cada fase que se pintan si vienen: ``(clave, plantilla)``. Solo se
# omiten las ausentes o nulas; un 0 es una cifra.
_CAMPOS_RESUMEN: dict[str, tuple[tuple[str, str], ...]] = {
    "baja": (
        ("filas", "{} filas"),
        ("serving", "serving {}"),
        ("degradado", "**degradado: {}**"),
        ("conformal_offset_baseline", "offset conformal {}"),
    ),
    "baja_por_lote": (
        ("filas", "{} filas"),
        ("serving", "serving {}"),
        ("degradado", "**degradado: {}**"),
    ),
    "retencion": (
        ("filas", "{} filas"),
        ("serving", "serving {}"),
        ("degradado", "**degradado: {}**"),
        ("purgadas", "{} purgadas"),
        ("resueltos_detectados", "{} resueltos detectados"),
    ),
    "drift": (
        ("regimen_servido", "régimen {}"),
        ("alerta", "alerta {}"),
    ),
    "calibracion": (
        ("cobertura", "cobertura {}"),
        ("n", "n {}"),
        ("mae_p50", "mae_p50 {}"),
        ("regimen_servido", "régimen {}"),
    ),
}

_SIN_DATO = "—"

# Un mensaje de error puede traer una traza entera; en una celda sobra.
_MAX_CELDA = 160


def _como_dict(valor: object) -> dict[str, Any]:
    return valor if isinstance(valor, dict) else {}


def _celda(texto: str) -> str:
    """``texto`` apto para una celda de tabla Markdown: sin ``|`` ni saltos."""
    limpio = " ".join(texto.replace("|", "\\|").split())
    return limpio if len(limpio) <= _MAX_CELDA else limpio[: _MAX_CELDA - 3] + "..."


def _valor(valor: object) -> str:
    if isinstance(valor, bool):
        return "sí" if valor else "no"
    if isinstance(valor, float):
        return str(round(valor, 4))
    return _celda(str(valor))


def _detalle_fase(fase: str, bloque: dict[str, Any]) -> list[str]:
    partes: list[str] = []
    if fase == "drift" and bloque.get("psi_max") is not None:
        peor = bloque.get("psi_peor_feature")
        psi = f"PSI máx {_valor(bloque['psi_max'])}"
        partes.append(f"{psi} ({_valor(peor)})" if peor else psi)
    for clave, plantilla in _CAMPOS_RESUMEN.get(fase, ()):
        valor = bloque.get(clave)
        if valor is not None and valor != "":
            partes.append(plantilla.format(_valor(valor)))
    if bloque.get("error"):
        partes.append(f"error: {_valor(bloque['error'])}")
    return partes


def _fila_purgas(purga: dict[str, Any]) -> tuple[str, list[str]]:
    """``(estado, partes)`` de las dos purgas, que comparten fila."""
    estados: list[object] = []
    partes: list[str] = []
    for clave, etiqueta in (("cerradas", "cerradas"), ("sin_adjudicar", "sin adjudicar")):
        sub = _como_dict(purga.get(clave))
        if not sub:
            continue
        estados.append(sub.get("status"))
        texto = f"{etiqueta}: {_valor(sub.get('borradas', 0))} borradas"
        if sub.get("error"):
            texto += f" (error: {_valor(sub['error'])})"
        partes.append(texto)
    if not estados:
        return _SIN_DATO, partes
    return ("ok" if all(e == "ok" for e in estados) else "error"), partes


def resumen_markdown(resumen: dict[str, Any]) -> str:
    """Resumen Markdown de una corrida de :func:`run_scoring` para el job.

    Una fila por fase con su estado, las cifras que responden "¿qué se sirvió
    y qué cambió?" y cuánto tardó, más el total. Defensivo con las claves: los
    monitores devuelven ``error`` o ``sin_datos`` sin cifras, y una fase que
    falte sale con ``—``. Función pura para poder testearla sin Actions.
    """
    duraciones = _como_dict(resumen.get("duraciones_s"))

    def duracion(fase: str) -> str:
        segundos = duraciones.get(fase)
        return _SIN_DATO if segundos is None else f"{_valor(segundos)} s"

    lineas = ["### ML scoring", ""]
    computed_at = _como_dict(resumen.get("baja")).get("computed_at")
    if computed_at:
        lineas += [f"Corrida de baja: `{_valor(computed_at)}`", ""]
    lineas += ["| Fase | Estado | Detalle | Duración |", "|---|---|---|---|"]
    for fase, etiqueta in _FASES_RESUMEN:
        bloque = _como_dict(resumen.get(fase))
        if fase == "purga":
            estado, partes = _fila_purgas(bloque)
        else:
            status = bloque.get("status")
            estado = _SIN_DATO if status is None else _valor(status)
            partes = _detalle_fase(fase, bloque)
        detalle = " · ".join(partes) or _SIN_DATO
        lineas.append(f"| {etiqueta} | {estado} | {detalle} | {duracion(fase)} |")
    if "total" in duraciones:
        lineas.append(f"| **Total** | | | **{duracion('total')}** |")
    return "\n".join(lineas) + "\n"


def _publicar_scoring(resumen: dict[str, Any]) -> None:
    """Outputs para ``verify`` y resumen del job. Nunca tumba el batch.

    Las filas ya están escritas: un fallo aquí no puede poner en rojo una
    corrida buena. Sin outputs, verify avisa y cae a la comprobación de
    frescura.
    """
    try:
        _escribir_github_output(_salidas_scoring(_como_dict(resumen.get("baja"))))
    except Exception as exc:
        log.error("ml_scoring_github_output_failed", error=str(exc))
    try:
        _escribir_step_summary(resumen_markdown(resumen))
    except Exception as exc:
        log.warning("ml_scoring_step_summary_failed", error=str(exc))


def run_scoring_cli() -> int:
    """Ejecuta el batch de scoring y falla si el modelo de baja no completó.

    Falla también cuando el serving quedó **degradado**: hay una versión activa
    en ``model_versions`` pero se sirvió el baseline porque su artefacto no se
    pudo resolver o su layout de features no cuadra. Eso no es el baseline
    honesto del RFC (ese caso es "no hay modelo activo"), es un modelo activo
    que no está llegando a producción, y hasta 2026-08 solo dejaba un
    ``log.warning`` en un job verde.

    Antes de decidir el código de salida publica los outputs que lee
    ``verify`` y el resumen de la corrida (:func:`_publicar_scoring`): el
    resumen importa sobre todo cuando el job sale en rojo.
    """
    from db.database import init_db

    init_db()
    resumen = run_scoring()
    baja = resumen.get("baja", {})
    retencion = resumen.get("retencion", {})
    status = baja.get("status")

    log.info(
        "ml_scoring_cli_done",
        baja_status=status,
        baja_serving=baja.get("serving"),
        baja_computed_at=baja.get("computed_at"),
        retencion_status=retencion.get("status"),
        drift=resumen.get("drift"),
        calibracion=resumen.get("calibracion"),
        purga=resumen.get("purga"),
        duraciones_s=resumen.get("duraciones_s"),
    )
    _publicar_scoring(resumen)

    if status not in _SCORING_OK_STATUSES:
        log.error("ml_scoring_cli_failed", baja=baja)
        return 1

    degradados = {
        modelo: resultado["degradado"]
        for modelo, resultado in (("baja", baja), ("retencion", retencion))
        if resultado.get("degradado")
    }
    if degradados:
        from observability.alerts import notify

        log.error("ml_scoring_serving_degradado", degradados=degradados)
        notify(
            "error",
            "ML scoring degradado a baseline",
            "Hay una versión activa en model_versions cuyo artefacto no se pudo "
            "servir; las predicciones publicadas son el baseline histórico. "
            "Revisá que train-predictivos.yml haya subido el .pkl a la Release.",
            **degradados,
        )
        return 1
    return 0


# ── Verify ────────────────────────────────────────────────────────────────────


def verify_predicciones_cli() -> int:
    """Verifica que ``predicciones_baja`` recibió las filas de **esta** corrida.

    Con los outputs del step de scoring en el entorno (``ml-scoring.yml`` los
    pasa siempre, vacíos si el scoring no pudo escribirlos):

    - ``ML_VERIFY_COMPUTED_AT`` no vacío: las filas agregadas con ese
      ``computed_at`` exacto tienen que ser exactamente ``ML_VERIFY_FILAS``, y
      más de cero (:func:`_verificar_corrida`).
    - vacío y ``ML_VERIFY_FILAS=0``: ``sin_abiertas``; no hay nada que
      verificar.
    - vacío con cualquier otro ``ML_VERIFY_FILAS`` (vacío, o incoherente): el
      scoring no dejó outputs utilizables. Se avisa y se cae a la frescura: la
      falta de outputs no prueba por sí sola que el batch no escribiera.

    Sin ``ML_VERIFY_COMPUTED_AT`` en el entorno (uso manual, plano local)
    queda la comprobación de frescura de siempre (:func:`_verificar_frescura`).
    """
    from db.repositories.predicciones import PrediccionesRepository

    repo = PrediccionesRepository()
    # Informativo: `predicciones_retencion` puede estar legítimamente vacía
    # (sin vencimientos en la ventana), así que no condiciona el código de
    # salida, pero sin loguearla no se sabe si el segundo modelo escribió.
    retencion = repo.estado("predicciones_retencion")
    log.info(
        "ml_scoring_verify",
        tabla="predicciones_retencion",
        filas=retencion["filas"],
        ultimo_computed_at=retencion["ultimo_computed_at"],
    )

    computed_at = os.environ.get("ML_VERIFY_COMPUTED_AT")
    if computed_at is None:
        return _verificar_frescura(repo)
    computed_at = computed_at.strip()
    filas = os.environ.get("ML_VERIFY_FILAS", "").strip()
    if computed_at:
        return _verificar_corrida(repo, computed_at, filas)
    if filas == "0":
        log.info("ml_scoring_verify_sin_abiertas", tabla="predicciones_baja")
        return 0
    log.warning("ml_scoring_verify_sin_outputs", tabla="predicciones_baja", filas=filas or None)
    return _verificar_frescura(repo)


def _verificar_corrida(repo: PrediccionesRepository, computed_at: str, filas: str) -> int:
    """Las filas con ``computed_at`` exacto son las que el batch dijo escribir.

    Es lo que la ventana de 26 h no podía afirmar: con el cron arrancando con
    hasta ~10 h de diferencia de un día a otro, "hay filas recientes" no
    distinguía la corrida de hoy de la de ayer
    (:meth:`PrediccionesRepository.contar_baja_de_corrida`). Se exige la cifra
    exacta y no "alguna fila": una corrida que escribió la mitad también deja
    filas con su ``computed_at``.
    """
    try:
        esperadas = int(filas)
    except ValueError:
        log.error(
            "ml_scoring_verify_filas_invalidas",
            tabla="predicciones_baja",
            computed_at=computed_at,
            filas=filas,
        )
        return 1
    escritas = repo.contar_baja_de_corrida(computed_at)
    log.info(
        "ml_scoring_verify",
        tabla="predicciones_baja",
        modo="corrida",
        computed_at=computed_at,
        filas_esperadas=esperadas,
        filas_escritas=escritas,
    )
    if esperadas <= 0 or escritas != esperadas:
        log.error(
            "ml_scoring_verify_corrida_incompleta",
            tabla="predicciones_baja",
            computed_at=computed_at,
            filas_esperadas=esperadas,
            filas_escritas=escritas,
        )
        return 1
    return 0


def _verificar_frescura(repo: PrediccionesRepository) -> int:
    """``predicciones_baja`` tiene filas y la más reciente no pasa de 26 h.

    Comprobar solo que la tabla tiene filas no verifica nada: el upsert de
    ``services/ml/scoring.py`` no purga, así que las filas de corridas
    anteriores sobreviven a un batch que no escribió ninguna.
    """
    estado = repo.estado("predicciones_baja")
    edad = _edad_horas(estado["ultimo_computed_at"])
    log.info(
        "ml_scoring_verify",
        tabla="predicciones_baja",
        modo="frescura",
        filas=estado["filas"],
        ultimo_computed_at=estado["ultimo_computed_at"],
        edad_horas=round(edad, 2) if edad is not None else None,
    )
    if not estado["filas"]:
        log.error("ml_scoring_verify_empty", tabla="predicciones_baja")
        return 1
    if edad is None:
        log.error(
            "ml_scoring_verify_sin_timestamp",
            tabla="predicciones_baja",
            ultimo_computed_at=estado["ultimo_computed_at"],
        )
        return 1
    if edad > _MAX_EDAD_PREDICCIONES_HORAS:
        log.error(
            "ml_scoring_verify_stale",
            tabla="predicciones_baja",
            edad_horas=round(edad, 2),
            maximo_horas=_MAX_EDAD_PREDICCIONES_HORAS,
        )
        return 1
    return 0


# ── Retrain ───────────────────────────────────────────────────────────────────


def run_retrain_cli() -> int:
    """Re-entrena los modelos predictivos y publica sus artefactos.

    Invocado por ``.github/workflows/train-predictivos.yml``. Escribe en
    ``$GITHUB_OUTPUT`` la lista de ficheros que el workflow debe subir a la
    Release: sin ese paso el ``.pkl`` muere con el runner efímero y la fila de
    ``model_versions`` apunta a una ruta que ningún job posterior puede
    resolver (era el motivo por el que ``ml-scoring`` servía baseline para
    siempre). Aquí un fallo al escribir el output sí se propaga: sin él no se
    sube nada.

    La activación de la versión nueva sigue siendo decisión humana vía
    ``db.model_registry`` salvo ``ML_PRED_AUTO_ACTIVATE``.
    """
    from pathlib import Path

    from db.database import init_db

    init_db()
    resultados = run_retrain()

    artefactos: list[str] = []
    fallidos: dict[str, Any] = {}
    for nombre, resumen in resultados.items():
        if resumen.get("status") not in _RETRAIN_OK_STATUSES:
            fallidos[nombre] = resumen
            continue
        ruta = resumen.get("path")
        if not ruta:
            continue
        pkl = Path(str(ruta))
        # El checksum co-ubicado lo escribe `save()`; viaja con el .pkl para
        # que `verify_model_integrity` pueda validar la carga en destino.
        artefactos.extend(str(p) for p in (pkl, pkl.with_suffix(".sha256")) if p.exists())

    log.info(
        "ml_retrain_cli_done",
        resultados={k: v.get("status") for k, v in resultados.items()},
        artefactos=artefactos,
    )
    _escribir_github_output({"artefactos": " ".join(artefactos)})

    if fallidos:
        log.error("ml_retrain_cli_failed", fallidos=fallidos)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Despacha el subcomando y cierra el pool Postgres pase lo que pase.

    Sin ``close_pool()`` el intérprete, al salir, espera a los hilos
    trabajadores de psycopg_pool, 5 s por hilo: el 2026-09-24 fueron 40 s en el
    scoring (8 hilos) y 20 s en el verify (4) de un job de 1.049 s con
    ``timeout-minutes: 20``. Mismo patrón que ``scraper/connectors/euskadi.py``.

    Returns:
        El código de salida del subcomando; 2 si no existe.
    """
    args = sys.argv[1:] if argv is None else argv
    cmd = args[0] if args else "scoring"
    subcomandos: dict[str, Callable[[], int]] = {
        "scoring": run_scoring_cli,
        "verify": verify_predicciones_cli,
        "retrain": run_retrain_cli,
        "debe-correr": debe_correr_cli,
    }
    ejecutar = subcomandos.get(cmd)
    if ejecutar is None:
        log.error("ml_predicciones_unknown_command", cmd=cmd, usage=_USO)
        return 2

    from db.database import close_pool

    try:
        return ejecutar()
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(main())
