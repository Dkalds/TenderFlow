"""Ejecutor del cierre de la pasada: en línea o por la cola de trabajo.

Recorre ``CANONICAL_STEPS`` respetando dependencias, resuelve cada paso contra
``scheduler.pipeline_pasos_impl``, avisa de los que fallan y cierra la ventana
de aviso de los que se recuperan. El camino por cola (S5.4) usa el mismo
:func:`ejecutar_paso` que el camino en línea.
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger
from scheduler import pipeline_pasos_impl
from scheduler.pipeline_pasos import (
    _LANE_AWARE_STEPS,
    CANONICAL_STEPS,
    LANE_BULK,
    LANE_DAILY,
    STEP_ERROR,
    STEP_OK,
    STEP_SKIPPED,
    STEP_SKIPPED_DEP,
    STEP_TIER,
    _contar_error,
    dependencias_incumplidas,
    pasos_bloqueantes_fallidos,
    step_tier,
)

# El nombre de antes de partir el módulo: `logger` sale en cada línea de log.
log = get_logger("scheduler.pipeline_runs")


class ColaNoDisponible(RuntimeError):
    """No se pudo ENCOLAR el cierre; ningún paso llegó a correr.

    Existe para que el cierre de la pasada no dependa de que la cola esté
    disponible: el camino por cola (S5.4) se estrenó con la revisión ``v106``, y
    entre desplegar el código y aplicar la migración hay una ventana en la que
    ``jobs`` todavía no existe. Sin esta distinción, esa ventana costaría los
    quince pasos del cierre —incluidas las alertas de vigilancia— en vez de
    costar solo la traza por paso en la BD.
    """


def _notify_step_failure(step: str, exc: Exception) -> None:
    """Alerta best-effort de un paso canónico fallido.

    Hasta 2026-08 un paso fallido solo dejaba una línea de log en un runner
    efímero de Actions: ningún notify(), ninguna métrica, exit code intacto.
    Así se ocultó semanas el cursor PSCP atascado. El plano APScheduler
    (loop.py) siempre alertó sus fallos; el plano activo no.

    Un paso que sigue roto avisa la primera vez y después una vez al día, no en
    cada pasada (``COOLDOWN_RECORDATORIO_DIARIO_S``). La ventana va por paso y
    la cierra :func:`_cerrar_avisos_de_pasos_recuperados` cuando el paso vuelve
    a terminar bien, así que una recaída avisa al momento.
    """
    try:
        from observability.alerts import COOLDOWN_RECORDATORIO_DIARIO_S, notify

        notify(
            "error",
            f"[pipeline] paso {step} falló",
            body=f"{type(exc).__name__}: {exc}"[:500],
            dedup_key=_clave_aviso_de_paso(step),
            cooldown_s=COOLDOWN_RECORDATORIO_DIARIO_S,
            step=step,
        )
    except Exception:
        # El aviso de un paso roto que no sale es el peor silencio posible: el
        # paso ya está en rojo y nadie se entera.
        _contar_error("aviso_paso")
        log.warning("pipeline_step_alert_failed", step=step, exc_info=True)


def _clave_aviso_de_paso(step: str) -> str:
    return f"pipeline_step:{step}"


def _cerrar_avisos_de_pasos_recuperados(results: dict[str, str]) -> None:
    """Cierra la ventana de aviso de los pasos que acaban de terminar ``ok``.

    Solo ``ok``: un paso ``skipped`` —apagado por flag, o periódico fuera de su
    día— o saltado por dependencia no ha demostrado que funcione. Best-effort,
    como el aviso que complementa.
    """
    try:
        from observability.alerts import cerrar_ventanas

        cerrar_ventanas(
            _clave_aviso_de_paso(name) for name, estado in results.items() if estado == STEP_OK
        )
    except Exception:
        _contar_error("cerrar_avisos")
        log.warning("pipeline_step_alert_close_failed", exc_info=True)


def _run_post_ingestion_steps(*, lane: str = LANE_BULK) -> dict[str, str]:
    """Ejecuta todos los pasos post-ingesta en orden canónico.

    ``CANONICAL_STEPS`` es la única fuente del orden: las implementaciones se
    resuelven por nombre contra ``scheduler.pipeline_pasos_impl`` (mantiene
    parcheable cada paso en tests). Antes existían dos literales — la constante y una lista de tuplas
    aquí — que había que sincronizar a mano y el checker de paridad solo leía
    la constante.

    Args:
        lane: ``LANE_DAILY`` o ``LANE_BULK``. Sólo lo reciben los pasos de
            ``_LANE_AWARE_STEPS``; el resto se ejecuta igual en ambos carriles.
            El default es el carril bulk — el permisivo — para que un caller
            que no lo declare no pierda trabajo en silencio.

    Returns:
        Dict ``{step_name: "ok" | "skipped" | "error"}`` con el resultado de
        cada paso. Un paso que devuelve la cadena ``"skipped"`` se reporta como
        tal (ver ``STEP_SKIPPED``): no hizo trabajo, pero tampoco falló. Los
        demás valores de retorno se ignoran y cuentan como ``"ok"`` — la
        mayoría de pasos no devuelven nada.
    """
    results: dict[str, str] = {}
    for name in CANONICAL_STEPS:
        # Mismo contrato que la comprobación de implementación: un paso sin
        # severidad declarada no puede ejecutarse, porque nadie habría decidido
        # si su fallo pone el job en rojo.
        step_tier(name)
        faltan = dependencias_incumplidas(name, results)
        if faltan:
            log.warning("pipeline_step_skipped_por_dependencia", step=name, dependencias=faltan)
            results[name] = STEP_SKIPPED_DEP
            continue
        try:
            results[name] = ejecutar_paso(name, lane=lane)
        except Exception as exc:
            log.exception("pipeline_step_failed", step=name, tier=STEP_TIER[name])
            results[name] = STEP_ERROR
            # Los advisory notifican igual: dejan de tumbar el job, no de avisar.
            _notify_step_failure(name, exc)

    _cerrar_avisos_de_pasos_recuperados(results)
    return results


def ejecutar_paso(name: str, *, lane: str = LANE_BULK) -> str:
    """Ejecuta UN paso canónico y devuelve ``ok``/``skipped``. Propaga el fallo.

    Es el único sitio donde se resuelve la implementación de un paso por su
    nombre, y por eso lo comparten los dos caminos del cierre: el que ejecuta en
    línea (:func:`_run_post_ingestion_steps`) y el que lo hace desde la cola
    (:func:`ejecutar_paso_encolado`). Si fueran dos resoluciones distintas, un
    paso podría comportarse de una manera dentro de la cola y de otra fuera.
    """
    fn = getattr(pipeline_pasos_impl, f"_run_{name}", None)
    if fn is None:
        raise RuntimeError(
            f"CANONICAL_STEPS contiene '{name}' sin implementación _run_{name} — "
            "la constante y las funciones de paso divergieron"
        )
    salida = fn(lane=lane) if name in _LANE_AWARE_STEPS else fn()
    return STEP_SKIPPED if salida == STEP_SKIPPED else STEP_OK


def ejecutar_paso_encolado(job: Any) -> dict[str, Any]:
    """Handler del tipo ``paso_pipeline`` de la cola (``services/jobs.py``).

    ``job`` es un ``services.jobs.Job``; se anota ``Any`` para no importar la cola
    al cargar este módulo, que es el que arrastra la pipeline entera y también
    se importa desde ``scripts/check_job_parity.py``.
    """
    nombre = str(job.payload["paso"])
    estado = ejecutar_paso(nombre, lane=str(job.payload.get("lane") or LANE_BULK))
    return {"paso": nombre, "estado": estado}


def _cierre_por_cola(*, lane: str) -> dict[str, str]:
    """Encola un job por paso canónico y los consume **en este mismo proceso**.

    Es la forma que pedía S5.4 y respeta ADR-012: GitHub Actions sigue siendo el
    único plano de cron, y el worker de Render ni siquiera reclama estos jobs
    (``claim`` filtra por tipo). Lo que gana el cierre es que cada paso deja una
    fila con su estado, su duración y su error: una pasada cortada a mitad se
    lee paso a paso en la BD en vez de reconstruirse del log de un runner
    efímero que ya no existe.

    Orden y dependencias: los jobs se encolan en el orden de ``CANONICAL_STEPS``
    —que sigue siendo la única fuente— y se reclaman por ``run_after, id``, así
    que salen en ese mismo orden. La comprobación de dependencias se hace sobre
    los resultados ya acumulados, igual que en el camino en línea.

    Restos de una pasada anterior: si un runner murió a mitad, sus jobs siguen
    ``pending`` y este bucle los reclamaría ANTES que los suyos (id menor). Se
    descartan explícitamente en vez de ejecutarlos, por dos motivos: el trabajo
    que representan lo va a hacer igualmente esta pasada con datos más frescos,
    y ejecutarlos rompería el orden canónico —``digests`` de la pasada vieja
    correría antes que ``watchlist_notify`` de esta—, que es justo la garantía
    sobre la que se apoya la comprobación de dependencias. Sin este descarte,
    además, los jobs recién encolados se quedaban sin consumir y la cola crecía
    una tanda por pasada.

    Raises:
        ColaNoDisponible: si falla el ENCOLADO, es decir antes de que ningún
            paso haya corrido. Quien llama vuelve entonces al camino en línea:
            que la cola no esté (una migración sin aplicar) no puede costar el
            cierre entero de la pasada.
    """
    from services.jobs import TIPO_PASO_PIPELINE, ack, claim, ejecutar, enqueue, fail

    tipos = (TIPO_PASO_PIPELINE,)

    # Los tiers se comprueban ANTES y fuera del try: un paso sin severidad
    # declarada es un error de programación del propio cierre —nadie decidió si
    # su fallo pone la pasada en rojo— y tiene que abortar igual que en el
    # camino en línea, no degradarse a «la cola no está disponible».
    for name in CANONICAL_STEPS:
        step_tier(name)

    mios: set[int] = set()
    try:
        for name in CANONICAL_STEPS:
            mios.add(enqueue(TIPO_PASO_PIPELINE, {"paso": name, "lane": lane}, deduplicar=False))
    except Exception as exc:
        raise ColaNoDisponible(f"no se pudo encolar el cierre: {exc}") from exc

    results: dict[str, str] = {}
    # Techo defensivo: además de los propios, el bucle puede encontrarse los
    # restos de una pasada anterior, y cada uno consume una vuelta.
    for _ in range(len(CANONICAL_STEPS) * 4):
        if len(results) >= len(mios):
            break
        job = claim("pipeline_cierre", tipos=tipos)
        if job is None:
            break
        nombre = str(job.payload.get("paso") or "")
        if job.id not in mios:
            log.warning(
                "pipeline_step_job_de_pasada_anterior_descartado", step=nombre, job_id=job.id
            )
            ack(job.id, {"paso": nombre, "estado": "descartado_pasada_anterior"})
            continue
        faltan = dependencias_incumplidas(nombre, results)
        if faltan:
            log.warning("pipeline_step_skipped_por_dependencia", step=nombre, dependencias=faltan)
            results[nombre] = STEP_SKIPPED_DEP
            ack(job.id, {"paso": nombre, "estado": STEP_SKIPPED_DEP, "dependencias": faltan})
            continue
        try:
            resultado = ejecutar(job)
        except Exception as exc:
            log.exception("pipeline_step_failed", step=nombre, tier=STEP_TIER.get(nombre))
            results[nombre] = STEP_ERROR
            fail(job.id, f"{type(exc).__name__}: {exc}", intentos=job.intentos, terminal=True)
            _notify_step_failure(nombre, exc)
            continue
        results[nombre] = str((resultado or {}).get("estado") or STEP_OK)
        ack(job.id, resultado)

    # No debería pasar —esta cola solo la consume este proceso; el worker filtra
    # por tipo—, pero un paso sin resultado desaparecería del resumen sin que
    # nada lo dijera, y «no salió en el informe» no puede significar «no pasó
    # nada».
    sin_consumir = [n for n in CANONICAL_STEPS if n not in results]
    if sin_consumir:
        log.warning("pipeline_cierre_pasos_sin_consumir", pasos=sin_consumir)

    _cerrar_avisos_de_pasos_recuperados(results)
    return results


def run_post_ingestion_only(
    *, lane: str = LANE_DAILY, via_cola: bool | None = None
) -> dict[str, Any]:
    """Solo el cierre de la pasada: los pasos post-ingesta, sin ingerir nada.

    Existe para que el workflow pueda ejecutar el cierre **después** de todos
    los conectores y no en medio de ellos.

    ``scrape-daily.yml`` corría ``run_update --daily`` —ingesta PLACSP *más*
    toda la secuencia canónica— y solo entonces lanzaba TED, Galicia, Euskadi,
    adjudicaciones vigiladas, PSCP y TACRC. O sea que el refresco de
    ``licitaciones_canonicas``, los KPIs precalculados y la evaluación de las
    reglas de vigilancia ocurrían antes de que cinco de las siete fuentes
    hubieran ingerido nada: su corpus del ciclo no entraba en la superficie
    pública, ni en los agregados, ni en las alertas hasta cuatro horas después.
    El contrato de ``db/repositories/publico.py`` dice que la vista se refresca
    «al final de la pasada de ingesta»; esta función es lo que hace que sea
    verdad.

    Args:
        lane: carril de la pasada (``daily``/``bulk``).
        via_cola: si el cierre encola sus pasos (S5.4) o los ejecuta en línea.
            ``None`` consulta ``JOBS_CIERRE_POR_COLA``, que por defecto es sí.
            Ponerlo a ``False`` es la salida de escape sin desplegar código.

    Returns:
        Dict con ``steps``, ``status`` (``ok`` si ningún paso **bloqueante**
        falló), ``advisory_failed`` (los pasos advisory en error, que sí
        notifican por email pero no degradan la pasada — ver ``STEP_TIER``) y
        ``skipped_por_dependencia`` (los que no llegaron a correr porque el paso
        del que dependen no dejó su insumo). Las dos listas van separadas a
        propósito: un advisory en error es «algo que avisar» y un salto por
        dependencia es «algo que ni se intentó», y meterlos en el mismo cubo
        haría creer que hubo quince intentos cuando hubo catorce.
    """
    from config.settings import jobs_cierre_por_cola

    usar_cola = jobs_cierre_por_cola() if via_cola is None else via_cola
    if usar_cola:
        try:
            step_results = _cierre_por_cola(lane=lane)
        except ColaNoDisponible as exc:
            # Degradación explícita y ruidosa. El cierre es lo que envía las
            # alertas de vigilancia y los digests: perderlo entero porque la
            # tabla `jobs` todavía no existe sería cambiar una mejora de
            # observabilidad por una caída de producto.
            log.warning("pipeline_cierre_cola_no_disponible", error=str(exc))
            step_results = _run_post_ingestion_steps(lane=lane)
    else:
        step_results = _run_post_ingestion_steps(lane=lane)

    fallidos = pasos_bloqueantes_fallidos(step_results)
    advisory = [
        name
        for name, estado in step_results.items()
        if estado == STEP_ERROR and name not in fallidos
    ]
    saltados = [name for name, estado in step_results.items() if estado == STEP_SKIPPED_DEP]
    if advisory:
        log.warning("pipeline_advisory_steps_failed", failed=advisory)
    if saltados:
        log.warning("pipeline_steps_skipped_por_dependencia", skipped=saltados)
    return {
        "status": "ok" if not fallidos else "degraded",
        "steps": step_results,
        "advisory_failed": advisory,
        "skipped_por_dependencia": saltados,
    }
