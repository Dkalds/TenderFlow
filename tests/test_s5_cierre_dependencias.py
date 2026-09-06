"""Cierre post-ingesta por pasos independientes (plan v2, S5.4).

Sin BD: se parchean los quince ``_run_<paso>`` y se ejercita el ejecutor en
línea, que es donde vive la lógica de dependencias que comparten los dos
caminos del cierre (en línea y por cola).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scheduler.pipeline_runs import (
    CANONICAL_STEPS,
    STEP_DEPS,
    STEP_ERROR,
    STEP_OK,
    STEP_SKIPPED,
    STEP_SKIPPED_DEP,
    _run_post_ingestion_steps,
    dependencias_incumplidas,
    pasos_bloqueantes_fallidos,
    run_post_ingestion_only,
)


def _patch_todos(**overrides: object) -> object:
    """Parchea los pasos canónicos; ``overrides`` sustituye alguno."""
    objetivos: dict[str, object] = {f"_run_{name}": MagicMock() for name in CANONICAL_STEPS}
    for nombre, valor in overrides.items():
        objetivos[f"_run_{nombre}"] = valor
    return patch.multiple("scheduler.pipeline_runs", **objetivos)


# ---------------------------------------------------------------------------
# El grafo de dependencias
# ---------------------------------------------------------------------------


def test_las_dependencias_declaradas_son_pasos_canonicos() -> None:
    """Una dependencia hacia un paso inexistente nunca se cumpliría."""
    for paso, deps in STEP_DEPS.items():
        assert paso in CANONICAL_STEPS, paso
        for dep in deps:
            assert dep in CANONICAL_STEPS, dep


def test_toda_dependencia_va_antes_que_su_paso_en_el_orden_canonico() -> None:
    """``CANONICAL_STEPS`` sigue siendo la ÚNICA fuente del orden.

    El ejecutor no reordena nada: comprueba dependencias contra lo ya
    ejecutado. Si una dependencia estuviera declarada después de su paso, la
    comprobación miraría un resultado que aún no existe y nunca frenaría nada,
    que es peor que no declararla — parecería que hay una garantía.
    """
    for paso, deps in STEP_DEPS.items():
        for dep in deps:
            assert CANONICAL_STEPS.index(dep) < CANONICAL_STEPS.index(paso), f"{dep} → {paso}"


def test_un_skipped_legitimo_no_arrastra_a_quien_depende() -> None:
    """Ventana de cadencia o flag apagado son estados correctos del sistema."""
    assert dependencias_incumplidas("digests", {"watchlist_notify": STEP_SKIPPED}) == []
    assert dependencias_incumplidas("digests", {"watchlist_notify": STEP_OK}) == []


def test_un_error_de_la_dependencia_si_arrastra() -> None:
    assert dependencias_incumplidas("digests", {"watchlist_notify": STEP_ERROR}) == [
        "watchlist_notify"
    ]


def test_el_arrastre_es_transitivo() -> None:
    """Un paso saltado por dependencia tampoco dejó su insumo."""
    assert dependencias_incumplidas("digests", {"watchlist_notify": STEP_SKIPPED_DEP}) == [
        "watchlist_notify"
    ]


# ---------------------------------------------------------------------------
# El criterio de aceptación: un bloqueante roto no arrastra a los ajenos
# ---------------------------------------------------------------------------


def test_kpi_precompute_roto_no_impide_watchlist_notify() -> None:
    """El criterio literal de S5.4.

    ``watchlist_notify`` no depende de ``kpi_precompute``: son el precálculo de
    KPIs y las alertas de vigilancia, y que uno se caiga no puede dejar sin
    avisar a quien está esperando una licitación.
    """
    with (
        _patch_todos(kpi_precompute=MagicMock(side_effect=RuntimeError("boom"))) as _,
        patch("scheduler.pipeline_runs._notify_step_failure"),
    ):
        results = _run_post_ingestion_steps()

    assert results["kpi_precompute"] == STEP_ERROR
    assert results["watchlist_notify"] == STEP_OK
    # Y los otros trece siguen teniendo un estado: nadie se queda sin correr.
    assert set(results) == set(CANONICAL_STEPS)


def test_una_dependencia_rota_si_frena_a_quien_depende() -> None:
    """``watchlist_notify`` acumula en ``pending_digests`` y ``digests`` envía."""
    with (
        _patch_todos(watchlist_notify=MagicMock(side_effect=RuntimeError("smtp"))),
        patch("scheduler.pipeline_runs._notify_step_failure"),
    ):
        results = _run_post_ingestion_steps()

    assert results["watchlist_notify"] == STEP_ERROR
    assert results["digests"] == STEP_SKIPPED_DEP
    # El paso saltado NO cuenta como fallo: no llegó a intentarse.
    assert pasos_bloqueantes_fallidos(results) == ["watchlist_notify"]


def test_un_paso_saltado_por_dependencia_no_se_ejecuta() -> None:
    digests = MagicMock()
    with (
        _patch_todos(
            watchlist_notify=MagicMock(side_effect=RuntimeError("smtp")),
            digests=digests,
        ),
        patch("scheduler.pipeline_runs._notify_step_failure"),
    ):
        _run_post_ingestion_steps()

    digests.assert_not_called()


def test_un_paso_saltado_por_dependencia_no_manda_email() -> None:
    """Un solo aviso por incidente: el del paso que falló de verdad."""
    with (
        _patch_todos(watchlist_notify=MagicMock(side_effect=RuntimeError("smtp"))),
        patch("scheduler.pipeline_runs._notify_step_failure") as notificar,
    ):
        _run_post_ingestion_steps()

    assert [c.args[0] for c in notificar.call_args_list] == ["watchlist_notify"]


# ---------------------------------------------------------------------------
# El resumen separa los dos cubos
# ---------------------------------------------------------------------------


def test_el_resumen_lista_skipped_por_dependencia_aparte_de_advisory_failed() -> None:
    """Criterio de S5.4: son cosas distintas y se cuentan por separado.

    ``via_cola=False`` para ejercitar el camino en línea sin BD; el camino por
    cola tiene su propio test de integración en ``test_s5_worker.py``.
    """
    with (
        _patch_todos(
            watchlist_notify=MagicMock(side_effect=RuntimeError("smtp")),
            drift_checks=MagicMock(side_effect=RuntimeError("psi")),
        ),
        patch("scheduler.pipeline_runs._notify_step_failure"),
    ):
        resumen = run_post_ingestion_only(via_cola=False)

    assert resumen["advisory_failed"] == ["drift_checks"]
    assert resumen["skipped_por_dependencia"] == ["digests"]
    assert resumen["status"] == "degraded"  # watchlist_notify es bloqueante


def test_sin_incidencias_las_dos_listas_van_vacias() -> None:
    with _patch_todos():
        resumen = run_post_ingestion_only(via_cola=False)

    assert resumen["status"] == "ok"
    assert resumen["advisory_failed"] == []
    assert resumen["skipped_por_dependencia"] == []


def test_el_cierre_por_cola_es_el_default_pero_se_puede_apagar() -> None:
    """``JOBS_CIERRE_POR_COLA`` es la salida de escape sin desplegar código."""
    from config.settings import jobs_cierre_por_cola

    assert jobs_cierre_por_cola() is True


def test_si_la_cola_no_esta_disponible_el_cierre_corre_igual_en_linea() -> None:
    """La ventana entre desplegar el código y aplicar ``v106`` no cuesta la pasada.

    Con la tabla ``jobs`` sin crear, ``enqueue`` revienta. Antes de este arreglo
    esa excepción subía hasta ``run_update`` y se llevaba por delante los quince
    pasos del cierre —alertas de vigilancia y digests incluidos— por un fallo de
    la traza, no del trabajo.
    """
    from scheduler import pipeline_runs

    with (
        _patch_todos(),
        patch(
            "shared.jobs.enqueue",
            side_effect=RuntimeError('relation "jobs" does not exist'),
        ),
    ):
        resumen = run_post_ingestion_only()

    assert resumen["status"] == "ok"
    assert set(resumen["steps"]) == set(pipeline_runs.CANONICAL_STEPS)


def test_la_cola_no_disponible_no_tapa_un_paso_sin_tier() -> None:
    """El fallback es para la cola, no para los errores del propio cierre.

    Un paso sin severidad declarada tiene que abortar en los dos caminos: si
    cayera al camino en línea, este volvería a comprobar el tier y a abortar,
    pero con un aviso que culpa a la cola de un problema que no es suyo.
    """
    from scheduler import pipeline_runs

    with (
        patch.object(pipeline_runs, "CANONICAL_STEPS", ["ml_scoring", "paso_sin_tier"]),
        patch.object(pipeline_runs, "_run_ml_scoring", MagicMock()),
        patch.object(pipeline_runs, "_run_paso_sin_tier", MagicMock(), create=True),
        patch("shared.jobs.enqueue") as encolar,
    ):
        try:
            pipeline_runs._cierre_por_cola(lane="daily")
        except pipeline_runs.ColaNoDisponible:  # pragma: no cover - el aserto de abajo
            raise AssertionError("un paso sin tier no es un problema de la cola") from None
        except RuntimeError as exc:
            assert "sin tier declarado" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("un paso sin tier debe abortar el cierre")

    encolar.assert_not_called()


def test_apagar_la_cola_por_entorno_devuelve_el_cierre_al_camino_en_linea(monkeypatch) -> None:
    monkeypatch.setenv("JOBS_CIERRE_POR_COLA", "0")
    with (
        _patch_todos(),
        patch("scheduler.pipeline_runs._cierre_por_cola") as por_cola,
    ):
        resumen = run_post_ingestion_only()

    por_cola.assert_not_called()
    assert resumen["status"] == "ok"


# ---------------------------------------------------------------------------
# Lo que S5.4 no puede romper
# ---------------------------------------------------------------------------


def test_el_ejecutor_sigue_exigiendo_un_tier_por_paso() -> None:
    """El test de tiers (``test_s2_step_tiers``) sigue siendo el contrato.

    Se reafirma aquí porque S5.4 metió una comprobación ANTES de ejecutar el
    paso, y colocarla antes de ``step_tier`` habría dejado correr un paso sin
    severidad declarada.
    """
    from scheduler import pipeline_runs

    with (
        patch.object(pipeline_runs, "CANONICAL_STEPS", ["ml_scoring", "paso_sin_tier"]),
        patch.object(pipeline_runs, "_run_ml_scoring", MagicMock()),
        patch.object(pipeline_runs, "_run_paso_sin_tier", MagicMock(), create=True),
    ):
        try:
            pipeline_runs._run_post_ingestion_steps()
        except RuntimeError as exc:
            assert "sin tier declarado" in str(exc)
        else:  # pragma: no cover - el fallo es el aserto de abajo
            raise AssertionError("un paso sin tier debe abortar el cierre")


def test_ejecutar_paso_es_el_unico_resolutor_de_implementaciones() -> None:
    """Los dos caminos del cierre resuelven el paso por el mismo sitio."""
    from scheduler.pipeline_runs import ejecutar_paso

    with patch("scheduler.pipeline_runs._run_kpi_precompute", MagicMock(return_value=None)):
        assert ejecutar_paso("kpi_precompute") == STEP_OK

    with patch("scheduler.pipeline_runs._run_ml_scoring", MagicMock(return_value=STEP_SKIPPED)):
        assert ejecutar_paso("ml_scoring") == STEP_SKIPPED


def test_ejecutar_paso_falla_si_la_constante_y_las_funciones_divergen() -> None:
    from scheduler.pipeline_runs import ejecutar_paso

    try:
        ejecutar_paso("un_paso_sin_implementacion")
    except RuntimeError as exc:
        assert "sin implementación" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("debe fallar")
