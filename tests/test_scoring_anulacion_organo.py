"""F1.4 — riesgo de anulación o desierto por órgano, sin BD.

El texto de ``organo_anula_frecuente`` existía en la explicación y la etiqueta
en el cliente, pero ningún camino del scoring emitía el flag. Aquí se fija la
regla: tasa ≥ 25 % con al menos diez expedientes resueltos, primero en el
CPV-4 y si no en el órgano entero; la penalización vive en
``SCORING_WEIGHTS`` y el perfil puede ponerla a cero.

El cálculo en SQL de la tasa está en
``tests/test_tasas_anulacion_integration.py``.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from services.analytics import scoring as sc_mod
from services.analytics.scoring import (
    ANULACION_MINIMO_EXPEDIENTES,
    FLAG_ANULACION,
    _effective_weights,
    _score_row,
    _ScoringContext,
    tasa_anulacion,
)
from services.analytics.scoring_signals import CompetenciaStats, MargenStats
from shared.scoring_weights import (
    PENALTY_MAX,
    dimension_weights,
    penalty_weights,
    validate_scoring_weights,
)

_AHORA = pd.Timestamp("2026-09-19T00:00:00Z")
_ORGANO = "Ayuntamiento de Anulaciones"
_CLAVE = _ORGANO.lower()

#: El fixture del plan: un órgano con el 40 % de anulaciones.
_TASAS_40 = {(_CLAVE, "*"): (20, 8)}


def _ctx(
    *, penalizacion: int = 8, tasas: dict[tuple[str, str], tuple[int, int]] | None = None
) -> _ScoringContext:
    return _ScoringContext(
        imp_p10=10_000.0,
        imp_p90=100_000.0,
        weights={"importe": 25, "plazo": 25, "competencia": 25, "margen": 25},
        keywords=[],
        affinity_scores={},
        affinity_method="unavailable",
        competencia_stats=CompetenciaStats(),
        margen_stats=MargenStats(),
        percentiles_fuente="universo_vivo",
        now=_AHORA,
        penalizacion_anulacion=penalizacion,
        tasas_anulacion=_TASAS_40 if tasas is None else tasas,
    )


def _row(**extra: Any) -> pd.Series:
    base = {
        "id_externo": "L1",
        "titulo": "Mantenimiento SAP",
        "importe": 50_000.0,
        "cpv": "72260000",
        "organo_contratacion": f"  {_ORGANO} ",
        "fecha_limite_dt": _AHORA + pd.Timedelta(days=30),
    }
    base.update(extra)
    return pd.Series(base)


class TestTasa:
    def test_el_cruce_con_el_cpv_gana_al_organo_entero(self) -> None:
        tasas = {(_CLAVE, "7226"): (10, 1), (_CLAVE, "*"): (50, 25)}
        assert tasa_anulacion(_ORGANO, "72260000", tasas) == (0.1, 10)

    def test_sin_muestra_en_el_cpv_cae_al_organo(self) -> None:
        tasas = {(_CLAVE, "7226"): (3, 3), (_CLAVE, "*"): (20, 8)}
        assert tasa_anulacion(_ORGANO, "72260000", tasas) == (0.4, 20)

    def test_por_debajo_del_minimo_no_hay_senal(self) -> None:
        n = ANULACION_MINIMO_EXPEDIENTES - 1
        tasas = {(_CLAVE, "7226"): (n, n), (_CLAVE, "*"): (n, n)}
        assert tasa_anulacion(_ORGANO, "72260000", tasas) is None

    def test_sin_organo(self) -> None:
        assert tasa_anulacion(None, "72260000", _TASAS_40) is None
        assert tasa_anulacion(float("nan"), "72260000", _TASAS_40) is None
        assert tasa_anulacion("   ", "72260000", _TASAS_40) is None


class TestScoreRow:
    def test_organo_con_40_por_ciento_lleva_flag_y_penaliza(self) -> None:
        con = _score_row(_row(), _ctx())
        sin = _score_row(_row(), _ctx(tasas={}))
        assert FLAG_ANULACION in con.flags
        assert FLAG_ANULACION not in sin.flags
        assert con.desglose["riesgo"] == sin.desglose["riesgo"] - 8
        assert any("anula o deja desiertos" in frase for frase in con.explicacion)

    def test_el_peso_es_el_que_se_resta(self) -> None:
        base = _score_row(_row(), _ctx(tasas={})).desglose["riesgo"]
        assert _score_row(_row(), _ctx(penalizacion=20)).desglose["riesgo"] == base - 20

    def test_peso_cero_apaga_la_senal(self) -> None:
        """Con peso 0 el flag diría «penaliza» sin penalizar."""
        fila = _score_row(_row(), _ctx(penalizacion=0))
        assert FLAG_ANULACION not in fila.flags

    def test_por_debajo_del_umbral_no_hay_flag(self) -> None:
        fila = _score_row(_row(), _ctx(tasas={(_CLAVE, "*"): (20, 4)}))  # 20 %
        assert FLAG_ANULACION not in fila.flags

    def test_consulta_caida_no_marca_nada(self) -> None:
        ctx = _ctx()
        ctx = _ScoringContext(**{**ctx.__dict__, "tasas_anulacion": None})
        assert FLAG_ANULACION not in _score_row(_row(), ctx).flags


class TestPesos:
    def test_la_penalizacion_no_cuenta_en_la_suma(self) -> None:
        validate_scoring_weights(
            {
                "importe": 20,
                "plazo": 15,
                "competencia": 20,
                "margen": 20,
                "afinidad": 15,
                "senal_tecnica": 10,
                FLAG_ANULACION: 8,
            }
        )

    def test_el_perfil_puede_ponerla_a_cero(self) -> None:
        validate_scoring_weights({"importe": 50, "plazo": 50, FLAG_ANULACION: 0})

    def test_tiene_techo(self) -> None:
        with pytest.raises(ValueError, match="máximo"):
            validate_scoring_weights({"importe": 100, FLAG_ANULACION: PENALTY_MAX + 1})

    def test_no_puede_ser_negativa(self) -> None:
        with pytest.raises(ValueError, match="negativo"):
            validate_scoring_weights({"importe": 100, FLAG_ANULACION: -1})

    def test_la_global_trae_la_penalizacion(self) -> None:
        from config import settings

        assert settings.SCORING_WEIGHTS[FLAG_ANULACION] > 0
        validate_scoring_weights(settings.SCORING_WEIGHTS, source="SCORING_WEIGHTS")

    def test_separacion(self) -> None:
        pesos = {"importe": 100, FLAG_ANULACION: 5}
        assert dimension_weights(pesos) == {"importe": 100}
        assert penalty_weights(pesos) == {FLAG_ANULACION: 5}

    def test_el_reparto_de_afinidad_no_toca_la_penalizacion(self) -> None:
        eff = _effective_weights({"importe": 50, "afinidad": 50, FLAG_ANULACION: 8}, [])
        assert eff == {"importe": 100}


class TestContexto:
    def _df(self) -> pd.DataFrame:
        return pd.DataFrame(
            [{"id_externo": "L1", "organo_contratacion": _ORGANO, "importe": 1.0, "titulo": "x"}]
        )

    def _build(self, profile: Any = None) -> _ScoringContext:
        with (
            patch.object(sc_mod, "load_competencia_stats", return_value=CompetenciaStats()),
            patch.object(sc_mod, "load_margen_stats", return_value=MargenStats()),
            patch.object(sc_mod._repo, "tech_signal_by_ids", return_value={}),
            patch(
                "db.repositories.tasas_anulacion.tasas_por_organos", return_value=_TASAS_40
            ) as consulta,
        ):
            ctx = sc_mod._build_context(self._df(), profile=profile)
        self.consulta = consulta
        return ctx

    def test_sin_perfil_usa_la_global(self) -> None:
        from config import settings

        ctx = self._build()
        assert ctx.penalizacion_anulacion == settings.SCORING_WEIGHTS[FLAG_ANULACION]
        assert ctx.tasas_anulacion == _TASAS_40
        self.consulta.assert_called_once_with([_CLAVE])
        assert FLAG_ANULACION not in ctx.weights

    def test_perfil_a_cero_no_paga_la_consulta(self) -> None:
        perfil = sc_mod.ScoringProfile(weights={"importe": 50, "plazo": 50, FLAG_ANULACION: 0})
        ctx = self._build(perfil)
        assert ctx.penalizacion_anulacion == 0
        self.consulta.assert_not_called()

    def test_perfil_anterior_a_la_penalizacion_hereda_la_global(self) -> None:
        from config import settings

        ctx = self._build(sc_mod.ScoringProfile(weights={"importe": 50, "plazo": 50}))
        assert ctx.penalizacion_anulacion == settings.SCORING_WEIGHTS[FLAG_ANULACION]


class TestPrecalculo:
    def test_un_fallo_de_las_tasas_es_parcial_y_no_frena_lo_demas(self) -> None:
        import scheduler.aggregates_precompute as ap

        with (
            patch.object(ap, "_recalcular_clusters", return_value=3),
            patch.object(ap, "refrescar_vista_canonicas", return_value=5),
            patch.object(ap, "record_event"),
            patch.object(ap, "_recalcular_tasas_anulacion", side_effect=RuntimeError("x")),
        ):
            resultado = ap.run_aggregates_precompute()
        assert resultado["status"] == "partial"
        assert resultado["error"] == "tasas_anulacion"
        assert (resultado["n_clusters"], resultado["n_canonicas"]) == (3, 5)

    def test_todo_bien(self) -> None:
        import scheduler.aggregates_precompute as ap

        with (
            patch.object(ap, "_recalcular_clusters", return_value=3),
            patch.object(ap, "refrescar_vista_canonicas", return_value=5),
            patch.object(ap, "record_event"),
            patch.object(ap, "_recalcular_tasas_anulacion", return_value=40),
        ):
            resultado = ap.run_aggregates_precompute()
        assert resultado["status"] == "ok"
        assert resultado["n_tasas_anulacion"] == 40


class TestMigracion:
    def _load(self) -> Any:
        return importlib.import_module("db.alembic.versions.v141_tasas_anulacion_organo")

    def test_cadena(self) -> None:
        mod = self._load()
        assert mod.revision == "v141_tasas_anulacion_organo"
        assert mod.down_revision == "v138_notice_type_code"

    def _op(self, dialecto: str) -> Any:
        llamadas: list[tuple[str, tuple[Any, ...]]] = []
        bind = SimpleNamespace(dialect=SimpleNamespace(name=dialecto))
        return SimpleNamespace(
            llamadas=llamadas,
            get_bind=lambda: bind,
            create_table=lambda *a, **k: llamadas.append(("create_table", a)),
            drop_table=lambda *a, **k: llamadas.append(("drop_table", a)),
        )

    def test_upgrade_crea_la_tabla_con_su_clave(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = self._load()
        op = self._op("postgresql")
        monkeypatch.setattr(mod, "op", op)
        mod.upgrade()
        ((nombre, args),) = op.llamadas
        assert nombre == "create_table"
        assert args[0] == "tasas_anulacion_organo"
        columnas = {c.name for c in args[1:] if hasattr(c, "name") and hasattr(c, "type")}
        assert {"organo_key", "cpv4", "n_expedientes", "n_fallidos", "tasa"} <= columnas

    def test_es_reversible(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = self._load()
        op = self._op("postgresql")
        monkeypatch.setattr(mod, "op", op)
        mod.downgrade()
        assert op.llamadas == [("drop_table", ("tasas_anulacion_organo",))]

    def test_fuera_de_postgres_no_hace_nada(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = self._load()
        op = self._op("sqlite")
        monkeypatch.setattr(mod, "op", op)
        mod.upgrade()
        mod.downgrade()
        assert op.llamadas == []
