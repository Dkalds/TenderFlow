"""Gate de promoción único y evaluación honesta del golden set.

Fija tres invariantes que el código violaba:

- El gate comparaba ``f1``/``pr_auc``/``brier`` de dos modelos medidos **cada
  uno sobre su propio test split**, recalculado en cada reentrenamiento sobre
  un dataset que crece. Eso no compara modelos: compara conjuntos de
  evaluación. Ahora la decisión la toma el golden set humano, que es fijo.
- Gateaba sobre etiquetas derivadas del filtro de keywords, así que un modelo
  que se limita a reproducir el regex pasaba con nota. ``recall_no_keyword``
  —lo único que mide valor incremental— se guardaba pero no bloqueaba.
- El umbral se elegía y se reportaba sobre el mismo golden set de 27 ejemplos.
"""

from __future__ import annotations

import hashlib

import pytest

from services.ml.promotion import MIN_RECALL_NO_KEYWORD, evaluar_gate
from services.ml_eval import (
    SPLIT_HOLDOUT,
    SPLIT_TUNE,
    GoldenExample,
    asignar_splits,
    evaluate_probas,
    filtrar_split,
    metricas_operativas,
)

_METRICAS_OK: dict[str, object] = {
    "f1": 0.90,
    "pr_auc": 0.92,
    "brier": 0.08,
    "n_test": 400,
    "n_positive_test": 120,
    "metrics_reliable": True,
    "split_strategy": "temporal",
}


def _golden(recall_no_kw: float, n_no_kw_pos: int = 30) -> object:
    """Construye un GoldenEvalResult con el recall incremental pedido.

    Con 30 positivos sin keyword y 30 negativos son 60 ejemplos: justo el mínimo
    de holdout (`MIN_HOLDOUT_EXAMPLES`) que el gate exige.
    """
    y_true = [1] * n_no_kw_pos + [0] * n_no_kw_pos
    aciertos = round(recall_no_kw * n_no_kw_pos)
    y_proba = [0.9] * aciertos + [0.1] * (n_no_kw_pos - aciertos) + [0.1] * n_no_kw_pos
    kw = [False] * n_no_kw_pos + [False] * n_no_kw_pos
    return evaluate_probas(y_true, y_proba, keyword_match=kw, threshold=0.5)


class TestGateDeCalidad:
    def test_un_modelo_bueno_pasa(self) -> None:
        assert evaluar_gate(_METRICAS_OK, metricas_activas=None, golden=_golden(0.60)) == []

    def test_bloquea_si_no_aporta_sobre_las_keywords(self) -> None:
        # Un modelo que solo replica matches_sap() tiene recall_no_keyword ≈ 0:
        # servir el regex es más barato que servir un pickle que hace lo mismo.
        motivos = evaluar_gate(_METRICAS_OK, metricas_activas=None, golden=_golden(0.0))
        assert any("recall_no_keyword" in m for m in motivos), motivos

    def test_el_umbral_de_aporte_minimo_es_el_documentado(self) -> None:
        justo_debajo = _golden(MIN_RECALL_NO_KEYWORD / 2, n_no_kw_pos=20)
        assert any(
            "recall_no_keyword" in m
            for m in evaluar_gate(_METRICAS_OK, metricas_activas=None, golden=justo_debajo)
        )

    def test_bloquea_si_las_metricas_no_son_fiables(self) -> None:
        # Un f1 a cuatro decimales sobre 8 filas de test no es una medición.
        metricas = {**_METRICAS_OK, "metrics_reliable": False, "n_test": 8}
        motivos = evaluar_gate(metricas, metricas_activas=None, golden=_golden(0.60))
        assert any("metricas_no_fiables" in m for m in motivos), motivos

    def test_bloquea_sin_golden_set(self) -> None:
        motivos = evaluar_gate(_METRICAS_OK, metricas_activas=None, golden=None)
        assert any("sin_golden_set" in m for m in motivos), motivos

    def test_bloquea_si_el_golden_no_tiene_zona_de_desacuerdo(self) -> None:
        vacio = evaluate_probas([1, 0], [0.9, 0.1], keyword_match=[True, True], threshold=0.5)
        motivos = evaluar_gate(_METRICAS_OK, metricas_activas=None, golden=vacio)
        assert any("zona_de_desacuerdo" in m for m in motivos), motivos

    def test_bloquea_si_el_recall_incremental_cae_frente_al_activo(self) -> None:
        motivos = evaluar_gate(
            _METRICAS_OK,
            metricas_activas=None,
            golden=_golden(0.30),
            golden_activo=_golden(0.70),
        )
        assert any("cae" in m for m in motivos), motivos

    def test_bloquea_si_el_holdout_es_demasiado_pequeno(self) -> None:
        """Con 40 ejemplos un acierto de más mueve el recall varios puntos."""
        pequeno = _golden(0.60, n_no_kw_pos=20)
        assert pequeno.n == 40
        motivos = evaluar_gate(_METRICAS_OK, metricas_activas=None, golden=pequeno)
        assert any("golden_holdout_insuficiente" in m and "40" in m for m in motivos), motivos

    def test_el_minimo_de_holdout_es_el_de_ml_eval(self) -> None:
        from services.ml_eval import MIN_HOLDOUT_EXAMPLES

        justo = _golden(0.60, n_no_kw_pos=MIN_HOLDOUT_EXAMPLES // 2)
        assert justo.n == MIN_HOLDOUT_EXAMPLES
        assert evaluar_gate(_METRICAS_OK, metricas_activas=None, golden=justo) == []

    def test_bloquea_si_el_activo_no_se_pudo_evaluar(self) -> None:
        """Hay versión activa y no se pudo medir: no se compara en silencio."""
        motivos = evaluar_gate(
            _METRICAS_OK,
            metricas_activas=None,
            golden=_golden(0.60),
            activo_no_evaluable="el artefacto de la versión activa no se pudo resolver",
        )
        assert any(m.startswith("activo_no_evaluable") for m in motivos), motivos

    def test_detecta_regresion_en_el_test_split(self) -> None:
        motivos = evaluar_gate(
            {**_METRICAS_OK, "f1": 0.70},
            metricas_activas={"f1": 0.90, "pr_auc": 0.92, "brier": 0.08},
            golden=_golden(0.60),
        )
        assert any(m.startswith("f1") for m in motivos), motivos


class TestSplitDelGoldenSet:
    def _ejemplos(self, n: int) -> list[GoldenExample]:
        return [
            GoldenExample(id=f"ej-{i}", titulo=f"t{i}", descripcion="", label=i % 2)
            for i in range(n)
        ]

    def test_tune_y_holdout_son_disjuntos_y_cubren_todo(self) -> None:
        asignados = asignar_splits(self._ejemplos(200))
        tune = {e.id for e in filtrar_split(asignados, SPLIT_TUNE)}
        holdout = {e.id for e in filtrar_split(asignados, SPLIT_HOLDOUT)}
        assert not (tune & holdout)
        assert len(tune) + len(holdout) == 200

    def test_la_asignacion_es_estable(self) -> None:
        primera = {e.id: e.split for e in asignar_splits(self._ejemplos(100))}
        segunda = {e.id: e.split for e in asignar_splits(self._ejemplos(100))}
        assert primera == segunda

    def test_añadir_ejemplos_no_reasigna_los_existentes(self) -> None:
        # Si ampliar el golden set reasignara las mitades, cada ampliación
        # invalidaría la comparación con las métricas anteriores.
        antes = {e.id: e.split for e in asignar_splits(self._ejemplos(100))}
        despues = {e.id: e.split for e in asignar_splits(self._ejemplos(300))}
        for ident, split in antes.items():
            assert despues[ident] == split

    def test_el_split_explicito_del_jsonl_se_respeta(self) -> None:
        ejemplos = [
            GoldenExample(id="a", titulo="t", descripcion="", label=1, split=SPLIT_TUNE),
            GoldenExample(id="b", titulo="t", descripcion="", label=0, split=SPLIT_HOLDOUT),
        ]
        asignados = {e.id: e.split for e in asignar_splits(ejemplos)}
        assert asignados == {"a": SPLIT_TUNE, "b": SPLIT_HOLDOUT}

    def test_el_reparto_es_aproximadamente_mitad_y_mitad(self) -> None:
        asignados = asignar_splits(self._ejemplos(1000))
        n_tune = len(filtrar_split(asignados, SPLIT_TUNE))
        assert 400 <= n_tune <= 600, n_tune


class TestMetricasOperativas:
    def test_precision_at_k_mira_la_cabeza_de_la_cola(self) -> None:
        # 5 relevantes en las 5 primeras posiciones → precision@5 = 1.0
        y = [1] * 5 + [0] * 15
        proba = [0.9 - i * 0.01 for i in range(20)]
        out = metricas_operativas(y, proba, ks=(5, 10))
        assert out["precision_at_5"] == 1.0
        assert out["precision_at_10"] == 0.5

    def test_recall_a_precision_fija(self) -> None:
        y = [1, 1, 1, 0, 0, 0]
        proba = [0.9, 0.8, 0.7, 0.2, 0.1, 0.05]
        out = metricas_operativas(y, proba, precisiones_objetivo=(0.9,))
        assert out["recall_at_precision_90"] == 1.0

    def test_el_coste_esperado_usa_la_asimetria_configurada(self) -> None:
        # Con FN mucho más caro que FP, el umbral de coste mínimo baja.
        y = [1, 1, 0, 0]
        proba = [0.6, 0.4, 0.35, 0.1]
        caro_fn = metricas_operativas(y, proba, cost_fp=1.0, cost_fn=10.0)
        caro_fp = metricas_operativas(y, proba, cost_fp=10.0, cost_fn=1.0)
        assert caro_fn["coste_esperado_min_threshold"] <= caro_fp["coste_esperado_min_threshold"]

    def test_conjunto_vacio_no_revienta(self) -> None:
        assert metricas_operativas([], []) == {}


# ---------------------------------------------------------------------------
# Qué `path` queda registrado (2026-09)
# ---------------------------------------------------------------------------
#
# `_download_release_asset` busca el asset por el nombre EXACTO de
# `Path(model_versions.path).name`. Registrando el artefacto versionado, el
# registro pedía `sap_classifier_v{N}.pkl` mientras `train-model.yml` subía
# `sap_classifier.pkl`: la resolución moría en `asset_not_in_release` y el
# scoring de la pipeline volvía a `no_model`. Se registra el publicado.


_CONTENIDO_FALSO = b"artefacto-entrenado"
_SHA_FALSO = hashlib.sha256(_CONTENIDO_FALSO).hexdigest()


class _ClfFalso:
    """Mínimo que `promote_if_better` le pide a un clasificador: `save`."""

    def save(self, path):
        from pathlib import Path as _P

        destino = _P(path)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(_CONTENIDO_FALSO)
        return destino


def _promocionar(tmp_path, *, motivos, activa=None, siguiente=1, registrada=None, **kwargs):
    """Corre `promote_if_better` con el registro y el gate mockeados.

    ``siguiente`` es lo que el registro dice que toca (el máximo de TODAS las
    filas más uno) y ``registrada`` lo que `register_version` acaba asignando.
    Por defecto coinciden, que es lo que pasa si nadie registra entre medias.
    ``kwargs`` llega tal cual a `promote_if_better`.
    """
    from unittest.mock import patch

    from services.ml.promotion import promote_if_better

    base = tmp_path / "publicado" / "sap_classifier.pkl"
    # Lo que el gate publica: la ruta base con el sha256 del contenido en el
    # nombre (`services.ml.model_artifacts.content_addressed_path`).
    publicado = tmp_path / "publicado" / f"sap_classifier-{_SHA_FALSO[:12]}.pkl"
    with (
        patch("db.model_registry.get_active", return_value=activa),
        patch("db.model_registry.next_version", return_value=siguiente),
        patch(
            "db.model_registry.register_version",
            return_value=siguiente if registrada is None else registrada,
        ) as register,
        patch("services.ml.promotion.evaluar_gate", return_value=motivos),
        patch("services.ml.promotion.evaluar_en_golden", return_value=None),
        # Sin esto, una `activa` con path ajeno saldría a la red (bucket y
        # Release) a por su artefacto; la resolución se prueba aparte.
        patch("services.ml.promotion._golden_del_activo", return_value=(None, None)),
    ):
        resultado = promote_if_better(
            _ClfFalso(),
            {"n_train": 100, "n_test": 50},
            models_dir=tmp_path / "versiones",
            publicar_como=base,
            **kwargs,
        )
    return resultado, register, publicado


def test_al_promocionar_se_registra_el_artefacto_publicado(tmp_path):
    """El nombre registrado tiene que ser el que viaja a la Release."""
    resultado, register, publicado = _promocionar(tmp_path, motivos=[])

    assert resultado.pendiente_de_activar is True
    registrado = register.call_args.kwargs
    assert registrado["path"] == str(publicado)
    assert registrado["activate"] is False
    # Y el fichero publicado existe de verdad, con el mismo contenido.
    assert publicado.read_bytes() == _CONTENIDO_FALSO
    assert resultado.artefacto == str(publicado)
    assert resultado.as_dict()["artefacto"] == str(publicado)


def test_el_publicado_lleva_el_sha256_en_el_nombre_y_no_pisa_el_fijo(tmp_path):
    """`sap_classifier-<sha12>.pkl` con su `.sha256`, y el de nombre fijo intacto.

    Con nombre fijo, subir el candidato sustituía el asset de la versión
    activa; y el `sap_classifier.pkl` local es lo que se sirve sin versión
    activa (`SAPClassifier.resolve_artifact`), así que tampoco se toca.
    """
    fijo = tmp_path / "publicado" / "sap_classifier.pkl"
    fijo.parent.mkdir(parents=True)
    fijo.write_bytes(b"modelo-de-mayo")

    _resultado, _register, publicado = _promocionar(tmp_path, motivos=[])

    assert publicado.name == f"sap_classifier-{_SHA_FALSO[:12]}.pkl"
    sidecar = publicado.with_suffix(".sha256")
    assert sidecar.read_text(encoding="utf-8").strip() == _SHA_FALSO
    assert fijo.read_bytes() == b"modelo-de-mayo"
    assert not fijo.with_suffix(".sha256").exists()


def test_el_sha_registrado_describe_el_fichero_publicado(tmp_path):
    """`publicar_como` es copia byte a byte, así que el hash sigue valiendo --
    es lo que verificará `resolve_active_artifact` tras bajarlo."""
    import hashlib

    _resultado, register, publicado = _promocionar(tmp_path, motivos=[])

    esperado = hashlib.sha256(publicado.read_bytes()).hexdigest()
    assert register.call_args.kwargs["sha256"] == esperado


def test_si_el_gate_rechaza_no_se_publica_y_se_registra_el_versionado(tmp_path):
    """Un rechazo no toca el artefacto que sirve producción, así que registrar
    su ruta sería mentir: la fila inactiva apunta al versionado."""
    resultado, register, publicado = _promocionar(tmp_path, motivos=["recall_no_keyword"])

    assert resultado.pendiente_de_activar is False
    assert not publicado.exists()
    registrado = register.call_args.kwargs
    assert registrado["path"].endswith("sap_classifier_v1.pkl")
    assert registrado["activate"] is False


# ---------------------------------------------------------------------------
# El gate no activa nunca (2026-10)
# ---------------------------------------------------------------------------
#
# `train-model.yml` sube el artefacto DESPUÉS del paso que entrena. Activando
# dentro de `promote_if_better`, un fallo entre los dos dejaba activa una
# versión sin artefacto publicado; y el reentrenamiento semanal la llamaba con
# el `activar=True` por defecto dentro de un runner efímero, que es como quedó
# activa la v2 del 2026-09-29. El candidato que pasa el gate se escribe y se
# registra, pero inactivo; lo activa
# `scheduler.jobs.ml_training_run.activar_publicada` tras cotejar la Release.


def test_el_candidato_que_pasa_se_publica_pero_no_se_activa(tmp_path):
    resultado, register, publicado = _promocionar(tmp_path, motivos=[])

    assert resultado.pendiente_de_activar is True
    registrado = register.call_args.kwargs
    assert registrado["activate"] is False
    # El fichero y la ruta registrada son los que el workflow va a subir: es
    # por ese nombre por el que se cotejará la Release antes de activar.
    assert registrado["path"] == str(publicado)
    assert publicado.read_bytes() == _CONTENIDO_FALSO
    assert resultado.as_dict()["pendiente_de_activar"] is True


def test_un_rechazo_no_queda_pendiente_de_activar(tmp_path):
    """Un rechazo no deja nada que subir."""
    resultado, register, publicado = _promocionar(tmp_path, motivos=["recall_no_keyword"])

    assert resultado.pendiente_de_activar is False
    assert "pendiente_de_activar" not in resultado.as_dict()
    assert "artefacto" not in resultado.as_dict()
    assert not publicado.exists()
    assert register.call_args.kwargs["activate"] is False


def test_no_hay_forma_de_pedirle_al_gate_que_active(tmp_path):
    """Ni por defecto ni pidiéndolo: el parámetro `activar` ya no existe.

    Un camino nuevo que quisiera activar en el acto tendría que pasar por
    `activar_publicada`, que antes coteja el sha256 con la Release.
    """
    with pytest.raises(TypeError):
        _promocionar(tmp_path, motivos=[], activar=True)

    resultado, _register, _publicado = _promocionar(tmp_path, motivos=[])
    assert "activada" not in resultado.as_dict()


# ---------------------------------------------------------------------------
# Qué número de versión lleva el candidato (2026-10)
# ---------------------------------------------------------------------------
#
# `promote_if_better` numeraba desde la versión ACTIVA (`activa + 1`, o 1 si no
# había ninguna) y `register_version` desde el máximo de TODAS las filas. Con
# una v1 registrada e inactiva (run 36609890015 de scrape-daily, 2026-09-29) el
# artefacto se guardó como `sap_classifier_v1.pkl`, los logs y la notificación
# dijeron «v1», y la fila insertada en `model_versions` fue la versión 2.


@pytest.mark.parametrize(
    "version_activa",
    [
        pytest.param(None, id="ninguna_activa"),
        # Tras un rollback con `activate_version` la activa queda por detrás
        # del máximo: `activa + 1` daría un número que ya existe.
        pytest.param(1, id="la_activa_no_es_la_ultima"),
    ],
)
def test_el_versionado_lleva_la_version_siguiente_al_maximo_registrado(tmp_path, version_activa):
    activa = None
    if version_activa is not None:
        activa = {
            "id": 7,
            "name": "sap_classifier",
            "version": version_activa,
            # No existe a propósito: sin fichero no hay golden del activo que
            # evaluar, y el gate va mockeado de todos modos.
            "path": str(tmp_path / "no-existe.pkl"),
            "sha256": "a" * 64,
            "trained_at": "2026-09-01T00:00:00+00:00",
            "trained_on_n_samples": 150,
            "trained_on_n_feedbacks": None,
            "is_active": 1,
            "notes": None,
            "metrics": {},
        }

    resultado, register, _publicado = _promocionar(
        tmp_path, motivos=["recall_no_keyword"], activa=activa, siguiente=3
    )

    versionados = sorted(p.name for p in (tmp_path / "versiones").iterdir())
    assert versionados == ["sap_classifier_v3.pkl"]
    assert register.call_args.kwargs["path"].endswith("sap_classifier_v3.pkl")
    assert resultado.version == 3


def test_el_resultado_lleva_la_version_que_asigno_el_registro(tmp_path):
    """`ResultadoPromocion.version` acaba en `$GITHUB_OUTPUT` y en la
    notificación: tiene que nombrar la fila que existe en `model_versions`. Si
    otro proceso registra entre la consulta y el INSERT, manda el INSERT."""
    resultado, _register, _publicado = _promocionar(tmp_path, motivos=[], siguiente=2, registrada=3)

    assert resultado.version == 3


def test_con_una_version_inactiva_registrada_el_candidato_es_la_v2(tmp_db, tmp_path):
    """El caso real, contra el registro de verdad: existe una v1 inactiva y
    ninguna activa. Fichero versionado, resultado y fila tienen que decir 2,
    y la v2 queda registrada pero sin activar: falta publicarla."""
    from unittest.mock import patch

    from db.model_registry import get_active, list_versions, register_version
    from services.ml.promotion import promote_if_better

    register_version(name="sap_classifier", path="data/models/sap_classifier_v1.pkl", sha256="a")
    assert get_active("sap_classifier") is None

    with (
        patch("services.ml.promotion.evaluar_gate", return_value=[]),
        patch("services.ml.promotion.evaluar_en_golden", return_value=None),
    ):
        resultado = promote_if_better(
            _ClfFalso(),
            {"n_train": 100, "n_test": 50},
            models_dir=tmp_path / "versiones",
            publicar_como=tmp_path / "publicado" / "sap_classifier.pkl",
        )

    assert resultado.version == 2
    assert [p.name for p in (tmp_path / "versiones").iterdir()] == ["sap_classifier_v2.pkl"]
    assert get_active("sap_classifier") is None
    v2 = next(f for f in list_versions("sap_classifier") if int(f["version"]) == 2)
    assert not v2["is_active"]


# ---------------------------------------------------------------------------
# Comparar contra el activo de verdad (2026-11, auditoría G2-2-1)
# ---------------------------------------------------------------------------
#
# El gate comparaba con la versión activa solo si `Path(activa["path"]).exists()`.
# Ese `path` es el del runner efímero que entrenó la versión, así que en CI la
# comparación no corría nunca y no dejaba ni una línea de log. Ahora se resuelve
# el artefacto activo (bucket/Release + sha256) y, si hay activa y no se puede
# medir, el candidato se rechaza.


def test_el_artefacto_activo_se_resuelve_por_el_registro_y_no_por_su_path():
    from unittest.mock import MagicMock, patch

    from services.ml.promotion import _golden_del_activo

    golden = _golden(0.70)
    with (
        patch(
            "services.ml.model_artifacts.resolve_active_artifact",
            return_value="data/models/activo.pkl",
        ) as resolver,
        patch("services.ml.sap_classifier.SAPClassifier.load", return_value=MagicMock()) as cargar,
        patch("services.ml.promotion.evaluar_en_golden", return_value=golden),
    ):
        medido, motivo = _golden_del_activo("sap_classifier")

    resolver.assert_called_once_with("sap_classifier")
    cargar.assert_called_once_with("data/models/activo.pkl")
    assert medido is golden
    assert motivo is None


def test_un_activo_irresoluble_se_declara_en_vez_de_saltarse():
    from unittest.mock import patch

    from services.ml.promotion import _golden_del_activo

    with patch("services.ml.model_artifacts.resolve_active_artifact", return_value=None):
        medido, motivo = _golden_del_activo("sap_classifier")

    assert medido is None
    assert motivo is not None


def test_un_activo_con_sha256_que_no_cuadra_tampoco_se_compara():
    from unittest.mock import patch

    from services.ml.model_artifacts import ModelArtifactMismatch
    from services.ml.promotion import _golden_del_activo

    with patch(
        "services.ml.model_artifacts.resolve_active_artifact",
        side_effect=ModelArtifactMismatch("sha256"),
    ):
        medido, motivo = _golden_del_activo("sap_classifier")

    assert medido is None
    assert motivo is not None
    assert "ModelArtifactMismatch" in motivo


def test_con_activa_no_evaluable_el_candidato_no_pasa_aunque_su_golden_sea_bueno(tmp_path):
    """Extremo a extremo del gate (sin mockear `evaluar_gate`): hay versión
    activa, no se puede medir, el candidato queda registrado pero rechazado."""
    from unittest.mock import patch

    from services.ml.promotion import promote_if_better

    activa = {
        "id": 7,
        "name": "sap_classifier",
        "version": 1,
        "path": "/runner/efimero/sap_classifier-aaaaaaaaaaaa.pkl",
        "sha256": "a" * 64,
        "metrics": {},
    }
    with (
        patch("db.model_registry.get_active", return_value=activa),
        patch("db.model_registry.next_version", return_value=2),
        patch("db.model_registry.register_version", return_value=2),
        patch("services.ml.promotion.evaluar_en_golden", return_value=_golden(0.60)),
        patch(
            "services.ml.promotion._golden_del_activo",
            return_value=(None, "el artefacto de la versión activa no se pudo resolver"),
        ),
    ):
        resultado = promote_if_better(
            _ClfFalso(),
            _METRICAS_OK,
            models_dir=tmp_path / "versiones",
            publicar_como=tmp_path / "publicado" / "sap_classifier.pkl",
        )

    assert resultado.pendiente_de_activar is False
    assert any(m.startswith("activo_no_evaluable") for m in resultado.motivos_rechazo)
    assert not (tmp_path / "publicado").exists()


def test_sin_version_activa_no_se_intenta_resolver_ningun_activo(tmp_path):
    from unittest.mock import patch

    from services.ml.promotion import promote_if_better

    with (
        patch("db.model_registry.get_active", return_value=None),
        patch("db.model_registry.next_version", return_value=1),
        patch("db.model_registry.register_version", return_value=1),
        patch("services.ml.promotion.evaluar_en_golden", return_value=_golden(0.60)),
        patch("services.ml.promotion._golden_del_activo") as medir_activo,
    ):
        resultado = promote_if_better(
            _ClfFalso(),
            _METRICAS_OK,
            models_dir=tmp_path / "versiones",
            publicar_como=tmp_path / "publicado" / "sap_classifier.pkl",
        )

    medir_activo.assert_not_called()
    assert resultado.pendiente_de_activar is True
