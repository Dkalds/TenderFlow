"""Tests del CLI de ``scheduler.jobs.ml_predicciones`` que orquesta ``ml-scoring.yml``.

El código de salida de cada subcomando está en
``test_unit_workflow_entrypoints.py``. Aquí va el resto del contrato con el
workflow: el guard de una corrida al día, los outputs que consume el verify,
el resumen del job, el cierre del pool y el cableado de ``run_scoring``
(features compartidas con el drift, purgas después de escribir, tiempos).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from scheduler.jobs import ml_predicciones as ml_job

_REPO = "db.repositories.predicciones.PrediccionesRepository"
_COMPUTED_AT = "2026-09-25T08:14:03.123456+00:00"


@pytest.fixture(autouse=True)
def _sin_entorno_actions(monkeypatch):
    """La suite corre dentro de GitHub Actions, donde estas variables existen.

    Sin limpiarlas, cada test del CLI escribiría sus outputs y su resumen en el
    step de CI que ejecuta pytest.
    """
    for nombre in (
        "GITHUB_OUTPUT",
        "GITHUB_STEP_SUMMARY",
        "ML_VERIFY_COMPUTED_AT",
        "ML_VERIFY_FILAS",
        "ML_SCORING_FORZAR",
    ):
        monkeypatch.delenv(nombre, raising=False)


def _outputs(ruta):
    return dict(linea.split("=", 1) for linea in ruta.read_text(encoding="utf-8").splitlines())


# ---------------------------------------------------------------------------
# debe_correr — una corrida por día UTC
# ---------------------------------------------------------------------------

_HOY = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)


def test_debe_correr_forzado_aunque_ya_se_puntuara_hoy():
    assert ml_job.debe_correr("2026-09-25T08:00:00+00:00", _HOY, forzar=True) == (True, "forzado")


@pytest.mark.parametrize("ultimo", [None, ""])
def test_debe_correr_sin_scoring_previo(ultimo):
    assert ml_job.debe_correr(ultimo, _HOY, forzar=False) == (True, "sin_scoring_previo")


@pytest.mark.parametrize(
    "ultimo",
    [
        "2026-09-25T08:00:00+00:00",
        "2026-09-25T08:00:00Z",
        "2026-09-25T00:00:00.000001+00:00",
        datetime(2026, 9, 25, 9, 59, tzinfo=UTC),
    ],
)
def test_debe_correr_salta_si_ya_se_puntuo_hoy(ultimo):
    assert ml_job.debe_correr(ultimo, _HOY, forzar=False) == (False, "ya_puntuado_hoy")


@pytest.mark.parametrize(
    "ultimo",
    [
        "2026-09-24T23:59:59.999999+00:00",
        "2026-09-20T12:00:00Z",
        datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
    ],
)
def test_debe_correr_primera_del_dia(ultimo):
    assert ml_job.debe_correr(ultimo, _HOY, forzar=False) == (True, "primera_del_dia")


def test_debe_correr_decide_por_dia_utc_y_no_por_horas_transcurridas():
    """20 min después pero otro día UTC corre; 23 h 50 min después el mismo día, no."""
    pasada_medianoche = datetime(2026, 9, 25, 0, 10, tzinfo=UTC)
    assert ml_job.debe_correr("2026-09-24T23:50:00+00:00", pasada_medianoche, forzar=False) == (
        True,
        "primera_del_dia",
    )
    casi_medianoche = datetime(2026, 9, 25, 23, 55, tzinfo=UTC)
    assert ml_job.debe_correr("2026-09-25T00:05:00+00:00", casi_medianoche, forzar=False) == (
        False,
        "ya_puntuado_hoy",
    )


def test_debe_correr_compara_en_utc_y_no_en_la_zona_de_cada_valor():
    """Las 01:30 del 25 en Madrid son las 23:30 UTC del 24: toca puntuar."""
    assert ml_job.debe_correr("2026-09-25T01:30:00+02:00", _HOY, forzar=False) == (
        True,
        "primera_del_dia",
    )
    # `ahora` también se lleva a UTC: la 01:00 del 26 en Madrid aún es el 25 UTC.
    ahora_madrid = datetime(2026, 9, 26, 1, 0, tzinfo=timezone(timedelta(hours=2)))
    assert ml_job.debe_correr("2026-09-25T08:00:00Z", ahora_madrid, forzar=False) == (
        False,
        "ya_puntuado_hoy",
    )


def test_debe_correr_sin_zona_horaria_es_utc():
    """Naive = UTC (lo que escribe ``now_utc_iso``), no la hora local del runner."""
    assert ml_job.debe_correr("2026-09-25T00:30:00", _HOY, forzar=False) == (
        False,
        "ya_puntuado_hoy",
    )
    assert ml_job.debe_correr(datetime(2026, 9, 24, 23, 30), _HOY, forzar=False) == (
        True,
        "primera_del_dia",
    )
    ahora_naive = datetime(2026, 9, 25, 23, 0)
    assert ml_job.debe_correr("2026-09-25T00:30:00Z", ahora_naive, forzar=False) == (
        False,
        "ya_puntuado_hoy",
    )


@pytest.mark.parametrize("ultimo", ["no-es-una-fecha", "2026-13-45", "ayer", 20260925, 3.5])
def test_debe_correr_corre_si_el_ultimo_es_ilegible(ultimo):
    """Ante la duda corre: saltarse el día en silencio es peor que puntuar dos veces."""
    assert ml_job.debe_correr(ultimo, _HOY, forzar=False) == (True, "ultimo_scoring_ilegible")


def test_debe_correr_corre_si_el_ultimo_es_de_un_dia_futuro():
    """Una sola fila con fecha futura fijaría el MAX y el guard saltaría todos los días."""
    assert ml_job.debe_correr("2099-01-01T00:00:00Z", _HOY, forzar=False) == (
        True,
        "ultimo_scoring_futuro",
    )


# ---------------------------------------------------------------------------
# debe-correr — el step de guard
# ---------------------------------------------------------------------------


def test_guard_cli_publica_correr_y_motivo(tmp_path, monkeypatch):
    salida = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(salida))
    estado = {"filas": 10, "ultimo_computed_at": _COMPUTED_AT}
    with (
        patch(f"{_REPO}.estado", return_value=estado),
        patch.object(ml_job, "debe_correr", return_value=(False, "ya_puntuado_hoy")) as decidir,
    ):
        assert ml_job.debe_correr_cli() == 0

    assert _outputs(salida) == {"correr": "false", "motivo": "ya_puntuado_hoy"}
    ultimo, ahora = decidir.call_args.args
    assert ultimo == _COMPUTED_AT
    assert ahora.tzinfo is not None
    assert decidir.call_args.kwargs == {"forzar": False}


def test_guard_cli_sin_scoring_previo_corre(tmp_path, monkeypatch):
    salida = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(salida))
    with patch(f"{_REPO}.estado", return_value={"filas": 0, "ultimo_computed_at": None}):
        assert ml_job.debe_correr_cli() == 0
    assert _outputs(salida) == {"correr": "true", "motivo": "sin_scoring_previo"}


def test_guard_cli_corre_si_no_puede_leer_la_bd(tmp_path, monkeypatch):
    """Fail-open: los steps reales enseñarán el error en vez de saltarse el día."""
    salida = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(salida))
    with patch(f"{_REPO}.estado", side_effect=RuntimeError("connection refused")):
        assert ml_job.debe_correr_cli() == 0
    assert _outputs(salida) == {"correr": "true", "motivo": "lectura_fallida"}


@pytest.mark.parametrize("valor", ["true", "TRUE", " True "])
def test_guard_cli_forzado_no_consulta_la_bd(tmp_path, monkeypatch, valor):
    salida = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(salida))
    monkeypatch.setenv("ML_SCORING_FORZAR", valor)
    with patch(f"{_REPO}.estado") as estado:
        assert ml_job.debe_correr_cli() == 0
    estado.assert_not_called()
    assert _outputs(salida) == {"correr": "true", "motivo": "forzado"}


@pytest.mark.parametrize("valor", ["false", "", "1", "yes"])
def test_guard_cli_solo_el_literal_true_fuerza(monkeypatch, valor):
    """El YAML pasa ``true``/``false`` (``github.event_name == 'workflow_dispatch'``)."""
    monkeypatch.setenv("ML_SCORING_FORZAR", valor)
    with (
        patch(f"{_REPO}.estado", return_value={"filas": 0, "ultimo_computed_at": None}) as estado,
        patch.object(ml_job, "debe_correr", return_value=(True, "x")) as decidir,
    ):
        assert ml_job.debe_correr_cli() == 0
    estado.assert_called_once()
    assert decidir.call_args.kwargs == {"forzar": False}


def test_guard_cli_fuera_de_actions_no_escribe_nada():
    with patch(f"{_REPO}.estado", return_value={"filas": 0, "ultimo_computed_at": None}):
        assert ml_job.debe_correr_cli() == 0


def test_guard_cli_en_rojo_si_no_puede_escribir_el_output(tmp_path, monkeypatch):
    """Sin ``correr`` el YAML saltaría todos los steps y el día se perdería en verde."""
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path))  # un directorio: open() falla
    with patch(f"{_REPO}.estado", return_value={"filas": 0, "ultimo_computed_at": None}):
        assert ml_job.debe_correr_cli() == 1


# ---------------------------------------------------------------------------
# scoring — outputs para el verify y resumen del job
# ---------------------------------------------------------------------------


def _resumen(**baja):
    return {
        "baja": {
            "status": "ok",
            "filas": 4414,
            "serving": "modelo",
            "degradado": None,
            "conformal_offset_baseline": None,
            "computed_at": _COMPUTED_AT,
            **baja,
        },
        "baja_por_lote": {"status": "desactivado"},
        "retencion": {
            "status": "baseline",
            "filas": 3003,
            "serving": "baseline",
            "degradado": None,
        },
        "drift": {"status": "ok", "psi_max": 0.0412, "psi_peor_feature": "plazo_dias"},
        "calibracion": {"status": "ok", "cobertura": 0.79, "n": 406, "mae_p50": 0.0512},
        "purga": {
            "cerradas": {"status": "ok", "borradas": 3, "corte": "2026-06-27"},
            "sin_adjudicar": {"status": "ok", "borradas": 220, "corte": "2025-09-30"},
        },
        "duraciones_s": {
            "baja": 135.2,
            "baja_por_lote": 0.0,
            "retencion": 60.4,
            "drift": 55.1,
            "calibracion": 4.0,
            "purga": 1.3,
            "total": 256.0,
        },
    }


def _scoring_cli(resumen):
    with (
        patch.object(ml_job, "run_scoring", return_value=resumen),
        patch("db.database.init_db"),
        patch("observability.alerts.notify"),
    ):
        return ml_job.run_scoring_cli()


def test_scoring_cli_publica_computed_at_y_filas_para_el_verify(tmp_path, monkeypatch):
    salida = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(salida))
    assert _scoring_cli(_resumen()) == 0
    assert _outputs(salida) == {"baja_computed_at": _COMPUTED_AT, "baja_filas": "4414"}


def test_scoring_cli_sin_abiertas_publica_cero_filas(tmp_path, monkeypatch):
    salida = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(salida))
    resumen = _resumen()
    resumen["baja"] = {"status": "sin_abiertas", "filas": 0, "granularidad": "expediente"}
    assert _scoring_cli(resumen) == 0
    assert _outputs(salida) == {"baja_computed_at": "", "baja_filas": "0"}


@pytest.mark.parametrize(
    "baja",
    [
        {"status": "error", "filas": 0},
        {"status": "ok", "filas": 12},  # sin computed_at: nada que contar
        {"status": "ok", "filas": 12, "computed_at": datetime(2026, 9, 25, tzinfo=UTC)},
    ],
)
def test_scoring_cli_nunca_publica_cero_sin_corrida_verificable(tmp_path, monkeypatch, baja):
    """Un ``0`` le diría al verify ``sin_abiertas`` y daría por buena la corrida."""
    salida = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(salida))
    resumen = _resumen()
    resumen["baja"] = baja
    _scoring_cli(resumen)
    assert _outputs(salida) == {"baja_computed_at": "", "baja_filas": ""}


def test_scoring_cli_escribe_el_resumen_tambien_en_rojo(tmp_path, monkeypatch):
    """El resumen importa sobre todo cuando el job falla."""
    resumen_md = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumen_md))
    resumen = _resumen(serving="baseline", degradado="artefacto_irresoluble")
    assert _scoring_cli(resumen) == 1
    texto = resumen_md.read_text(encoding="utf-8")
    assert texto.startswith("### ML scoring")
    assert "**degradado: artefacto_irresoluble**" in texto


def test_scoring_cli_sigue_si_no_puede_escribir_outputs_ni_resumen(tmp_path, monkeypatch):
    """Las filas ya están escritas: fallar al publicar no pone en rojo una corrida buena."""
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path))  # directorios: open() falla
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path))
    assert _scoring_cli(_resumen()) == 0


def test_scoring_cli_publica_outputs_aunque_el_resumen_reviente(tmp_path, monkeypatch):
    salida = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(salida))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    with patch.object(ml_job, "resumen_markdown", side_effect=KeyError("psi_max")):
        assert _scoring_cli(_resumen()) == 0
    assert _outputs(salida)["baja_filas"] == "4414"


def test_escribir_github_output_una_linea_por_clave(tmp_path, monkeypatch):
    salida = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(salida))
    ml_job._escribir_github_output({"motivo": "a\r\nb", "vacio": ""})
    assert salida.read_text(encoding="utf-8") == "motivo=a b\nvacio=\n"


# ---------------------------------------------------------------------------
# resumen_markdown
# ---------------------------------------------------------------------------


def _filas_tabla(markdown):
    """Filas de la tabla indexadas por la primera celda."""
    return {
        linea.split("|")[1].strip(): linea
        for linea in markdown.splitlines()
        if linea.startswith("| ")
    }


def test_resumen_markdown_pinta_cada_fase_con_sus_cifras():
    resumen = _resumen(conformal_offset_baseline=0.01234567)
    resumen["retencion"].update(purgadas=440, resueltos_detectados=12)
    resumen["drift"].update(regimen_servido="modelo", alerta="suprimida_regimen")
    resumen["calibracion"]["regimen_servido"] = "baseline"
    md = ml_job.resumen_markdown(resumen)

    assert md.startswith("### ML scoring\n")
    assert f"`{_COMPUTED_AT}`" in md
    filas = _filas_tabla(md)
    assert filas["Baja (agregada)"] == (
        "| Baja (agregada) | ok | 4414 filas · serving modelo · offset conformal 0.0123 | 135.2 s |"
    )
    assert filas["Baja por lote"] == "| Baja por lote | desactivado | — | 0.0 s |"
    assert "440 purgadas · 12 resueltos detectados" in filas["Retención"]
    assert filas["Drift"] == (
        "| Drift | ok | PSI máx 0.0412 (plazo_dias) · régimen modelo · "
        "alerta suprimida_regimen | 55.1 s |"
    )
    assert filas["Calibración"] == (
        "| Calibración | ok | cobertura 0.79 · n 406 · mae_p50 0.0512 · régimen baseline | 4.0 s |"
    )
    assert filas["Purgas"] == (
        "| Purgas | ok | cerradas: 3 borradas · sin adjudicar: 220 borradas | 1.3 s |"
    )
    assert filas["**Total**"] == "| **Total** | | | **256.0 s** |"


def test_resumen_markdown_tolera_monitores_sin_cifras():
    """``error``/``sin_datos`` no traen cifras; una fase ausente sale con guion."""
    md = ml_job.resumen_markdown(
        {
            "baja": {"status": "sin_abiertas", "filas": 0},
            "drift": {"status": "error", "error": "boom"},
            "calibracion": {"status": "sin_datos", "n": 12, "regimen_servido": None},
        }
    )
    filas = _filas_tabla(md)
    assert filas["Baja (agregada)"] == "| Baja (agregada) | sin_abiertas | 0 filas | — |"
    assert filas["Drift"] == "| Drift | error | error: boom | — |"
    assert filas["Calibración"] == "| Calibración | sin_datos | n 12 | — |"
    assert filas["Retención"] == "| Retención | — | — | — |"
    assert filas["Purgas"] == "| Purgas | — | — | — |"
    assert "Total" not in md
    assert "Corrida de baja" not in md


def test_resumen_markdown_de_un_resumen_vacio():
    filas = _filas_tabla(ml_job.resumen_markdown({}))
    # Cabecera + las seis fases, todas sin dato.
    assert len(filas) == 7


def test_resumen_markdown_marca_la_purga_que_fallo():
    md = ml_job.resumen_markdown(
        {
            "purga": {
                "cerradas": {"status": "error", "borradas": 0, "error": "lock timeout"},
                "sin_adjudicar": {"status": "ok", "borradas": 5},
            }
        }
    )
    assert _filas_tabla(md)["Purgas"] == (
        "| Purgas | error | cerradas: 0 borradas (error: lock timeout) · "
        "sin adjudicar: 5 borradas | — |"
    )


def test_resumen_markdown_no_rompe_la_tabla_con_errores_largos():
    error = "a | b\nTraceback (most recent call last):\n" + "x" * 500
    fila = _filas_tabla(ml_job.resumen_markdown({"drift": {"status": "error", "error": error}}))[
        "Drift"
    ]
    assert "a \\| b Traceback" in fila
    assert fila.endswith("... | — |")
    # Cinco separadores sin escapar: la fila sigue teniendo cuatro columnas.
    assert len(re.findall(r"(?<!\\)\|", fila)) == 5


# ---------------------------------------------------------------------------
# main — despacho y cierre del pool
# ---------------------------------------------------------------------------


def test_main_cierra_el_pool_aunque_el_subcomando_reviente():
    """Sin close_pool el intérprete espera 5 s por hilo del pool al salir."""
    with (
        patch.object(ml_job, "run_scoring_cli", side_effect=RuntimeError("boom")),
        patch("db.database.close_pool") as close_pool,
        pytest.raises(RuntimeError, match="boom"),
    ):
        ml_job.main(["scoring"])
    close_pool.assert_called_once_with()


@pytest.mark.parametrize(
    ("argv", "subcomando"),
    [
        ([], "run_scoring_cli"),
        (["scoring"], "run_scoring_cli"),
        (["verify"], "verify_predicciones_cli"),
        (["retrain"], "run_retrain_cli"),
        (["debe-correr"], "debe_correr_cli"),
    ],
)
def test_main_despacha_y_devuelve_el_codigo_del_subcomando(argv, subcomando):
    with (
        patch.object(ml_job, subcomando, return_value=7) as ejecutar,
        patch("db.database.close_pool") as close_pool,
    ):
        assert ml_job.main(argv) == 7
    ejecutar.assert_called_once_with()
    close_pool.assert_called_once_with()


def test_main_lee_sys_argv_por_defecto(monkeypatch):
    monkeypatch.setattr("sys.argv", ["ml_predicciones", "verify"])
    with (
        patch.object(ml_job, "verify_predicciones_cli", return_value=0) as verify,
        patch("db.database.close_pool"),
    ):
        assert ml_job.main() == 0
    verify.assert_called_once_with()


def test_main_subcomando_desconocido_sale_con_2():
    with patch("db.database.close_pool") as close_pool:
        assert ml_job.main(["puntuar"]) == 2
    close_pool.assert_not_called()


# ---------------------------------------------------------------------------
# run_scoring — cableado de las fases
# ---------------------------------------------------------------------------

_CORTE_VIVAS = "2025-09-30"


@pytest.fixture
def fases(monkeypatch):
    """Sustituye cada fase de ``run_scoring`` y anota el orden en que corren."""
    orden: list[str] = []
    filas = [object(), object()]

    def fase(nombre, resultado):
        def ejecutar(*_args, **_kwargs):
            orden.append(nombre)
            return resultado

        return MagicMock(side_effect=ejecutar)

    mocks = {
        "corte": fase("corte", _CORTE_VIVAS),
        "features": fase("features", filas),
        "baja": fase(
            "baja", {"status": "ok", "serving": "modelo", "filas": 2, "computed_at": _COMPUTED_AT}
        ),
        "por_lote": fase("por_lote", {"status": "desactivado"}),
        "retencion": fase("retencion", {"status": "baseline"}),
        "drift": fase("drift", {"status": "ok"}),
        "calibracion": fase("calibracion", {"status": "ok"}),
        "cerradas": fase("cerradas", {"status": "ok", "borradas": 1}),
        "sin_adjudicar": fase("sin_adjudicar", {"status": "ok", "borradas": 2}),
    }
    monkeypatch.setattr("services.ml.features.corte_abiertas_vivas", mocks["corte"])
    monkeypatch.setattr("services.ml.features.features_licitaciones_abiertas", mocks["features"])
    monkeypatch.setattr("services.ml.scoring.score_predicciones_baja", mocks["baja"])
    monkeypatch.setattr("services.ml.scoring.score_predicciones_retencion", mocks["retencion"])
    monkeypatch.setattr("services.ml.drift.comprobar_drift_baja", mocks["drift"])
    monkeypatch.setattr("services.ml.calibration.comprobar_calibracion_baja", mocks["calibracion"])
    monkeypatch.setattr(ml_job, "_score_baja_por_lote_si_activo", mocks["por_lote"])
    monkeypatch.setattr(ml_job, "purgar_predicciones_cerradas", mocks["cerradas"])
    monkeypatch.setattr(ml_job, "purgar_predicciones_sin_adjudicar", mocks["sin_adjudicar"])
    return filas, mocks, orden


def test_run_scoring_construye_las_features_una_vez_y_las_comparte_con_drift(fases):
    """El drift recalculaba las features por su cuenta: ~2 min del job del 2026-09-24."""
    filas, mocks, _ = fases
    ml_job.run_scoring()
    mocks["features"].assert_called_once_with()
    assert mocks["baja"].call_args.kwargs["filas"] is filas
    assert mocks["drift"].call_args.kwargs["scoring"] is filas
    assert mocks["drift"].call_args.kwargs["regimen"] == "modelo"


def test_run_scoring_sin_abiertas_no_tiene_regimen(fases):
    _, mocks, _ = fases
    mocks["baja"].side_effect = None
    mocks["baja"].return_value = {"status": "sin_abiertas", "filas": 0}
    ml_job.run_scoring()
    assert mocks["drift"].call_args.kwargs["regimen"] is None


def test_run_scoring_purga_despues_de_escribir_con_el_corte_del_inicio(fases):
    _, mocks, orden = fases
    resumen = ml_job.run_scoring()
    assert orden == [
        "corte",
        "features",
        "baja",
        "por_lote",
        "retencion",
        "drift",
        "calibracion",
        "cerradas",
        "sin_adjudicar",
    ]
    mocks["sin_adjudicar"].assert_called_once_with(_CORTE_VIVAS)
    assert resumen["purga"] == {
        "cerradas": {"status": "ok", "borradas": 1},
        "sin_adjudicar": {"status": "ok", "borradas": 2},
    }


def test_run_scoring_cronometra_cada_fase_con_un_decimal(fases, monkeypatch):
    class _Reloj:
        """Avanza 0,34 s por lectura: cada fase lee dos veces, el total una más."""

        t = 1000.0

        def monotonic(self):
            self.t += 0.34
            return self.t

    monkeypatch.setattr(ml_job, "time", _Reloj())
    resumen = ml_job.run_scoring()
    fases_esperadas = ("baja", "baja_por_lote", "retencion", "drift", "calibracion", "purga")
    assert resumen["duraciones_s"] == {**dict.fromkeys(fases_esperadas, 0.3), "total": 4.4}


def test_cronometrar_anota_la_fase_aunque_el_bloque_lance():
    """Si una fase revienta o el job muere por timeout, su duración queda en el log."""
    duraciones: dict[str, float] = {}
    with pytest.raises(RuntimeError), ml_job._cronometrar(duraciones, "retencion"):
        raise RuntimeError("statement timeout")
    assert "retencion" in duraciones


# ---------------------------------------------------------------------------
# purgar_predicciones_sin_adjudicar
# ---------------------------------------------------------------------------


def test_purga_sin_adjudicar_usa_el_corte_recibido():
    with patch(f"{_REPO}.purgar_sin_adjudicar", return_value=7) as purgar:
        resultado = ml_job.purgar_predicciones_sin_adjudicar(_CORTE_VIVAS)
    assert resultado == {"status": "ok", "borradas": 7, "corte": _CORTE_VIVAS}
    purgar.assert_called_once_with(antes_de=_CORTE_VIVAS)


def test_purga_sin_adjudicar_sin_corte_usa_el_de_la_poblacion():
    with (
        patch("services.ml.features.corte_abiertas_vivas", return_value="2025-09-29"),
        patch(f"{_REPO}.purgar_sin_adjudicar", return_value=0) as purgar,
    ):
        assert ml_job.purgar_predicciones_sin_adjudicar()["corte"] == "2025-09-29"
    purgar.assert_called_once_with(antes_de="2025-09-29")


def test_purga_sin_adjudicar_es_fail_open():
    """No haber borrado filas muertas nunca es peor que no publicar las nuevas."""
    with patch(f"{_REPO}.purgar_sin_adjudicar", side_effect=RuntimeError("lock timeout")):
        resultado = ml_job.purgar_predicciones_sin_adjudicar(_CORTE_VIVAS)
    assert resultado["status"] == "error"
    assert resultado["borradas"] == 0
    assert "lock timeout" in resultado["error"]
