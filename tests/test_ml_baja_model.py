"""Tests del modelo de baja y su scoring batch (Fase 6, RFC 20260611-2)."""

from __future__ import annotations

import hashlib

import pytest

import services.ml.baja_model as baja_model_mod
from config import settings
from services.ml.baja_model import (
    MODEL_NAME,
    BajaModel,
    entrenar,
    intervalo_baseline,
    offset_conformal_baseline,
    predecir_baseline,
)
from services.ml.features import FilaDataset
from services.ml.scoring import prediccion_baja, score_predicciones_baja


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _sembrar_historico(c, n_meses=14, por_mes=8):
    """Histórico sintético: órgano A baja ~10%, órgano B ~25%, con ruido."""
    i = 0
    for mes in range(n_meses):
        yyyy, mm = divmod(mes, 12)
        fecha = f"{2025 + yyyy}-{mm + 1:02d}-15"
        for k in range(por_mes):
            organo = "Organo A" if k % 2 == 0 else "Organo B"
            base = 0.10 if organo == "Organo A" else 0.25
            baja = base + (i % 7 - 3) * 0.005  # ruido determinista ±1.5%
            importe = 100_000.0 + (i % 5) * 50_000
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, "
                " ccaa, importe, tipo_contrato, fuente, fecha_publicacion, fecha_extraccion) "
                "VALUES (%s, %s, %s, '72000000', 'Madrid', %s, 'Servicios', 'placsp', %s, "
                " CURRENT_TIMESTAMP)",
                (f"H{i}", f"Contrato {i}", organo, importe, fecha),
            )
            c.execute(
                "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
                " fecha_adjudicacion, n_ofertas_recibidas, fecha_extraccion) "
                "VALUES (%s, 'Empresa X', %s, %s, 3, CURRENT_TIMESTAMP)",
                (f"H{i}", importe * (1 - baja), fecha),
            )
            i += 1
    return i


def _insertar_abierta(c, lic_id="ABIERTA", organo="Organo A"):
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
        " importe, estado, tipo_contrato, fuente, fecha_publicacion, fecha_extraccion) "
        "VALUES (%s, 'Nueva', %s, '72000000', 'Madrid', 300000, 'PUB', 'Servicios', "
        " 'placsp', '2026-06-01', CURRENT_TIMESTAMP)",
        (lic_id, organo),
    )


# ---------------------------------------------------------------------------
# Integridad del modelo serializado (pin out-of-band + checksum co-ubicado)
# ---------------------------------------------------------------------------


def _save_untrained(tmp_path):
    modelo = BajaModel(modelos={}, categorias={}, metadata={})
    model_path = tmp_path / "baja.pkl"
    modelo.save(model_path)  # escribe .pkl + .sha256 co-ubicado
    return model_path


def test_load_rejects_when_pin_mismatch(tmp_path, monkeypatch) -> None:
    model_path = _save_untrained(tmp_path)
    monkeypatch.setattr(settings, "ML_BAJA_MODEL_SHA256", "de" * 32)  # no coincide
    with pytest.raises(RuntimeError, match="ML_BAJA_MODEL_SHA256"):
        BajaModel.load(model_path)


def test_load_accepts_when_pin_matches(tmp_path, monkeypatch) -> None:
    model_path = _save_untrained(tmp_path)
    correct = hashlib.sha256(model_path.read_bytes()).hexdigest()
    monkeypatch.setattr(settings, "ML_BAJA_MODEL_SHA256", correct)
    assert BajaModel.load(model_path) is not None


def test_load_pin_detects_tampered_model(tmp_path, monkeypatch) -> None:
    """Pin del modelo original; luego se manipula el .pkl y su .sha256
    co-ubicado (simula un release comprometido). El pin debe detectarlo."""
    model_path = _save_untrained(tmp_path)
    original_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    monkeypatch.setattr(settings, "ML_BAJA_MODEL_SHA256", original_hash)

    model_path.write_bytes(b"contenido manipulado")
    tampered_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    model_path.with_suffix(".sha256").write_text(tampered_hash, encoding="utf-8")

    with pytest.raises(RuntimeError, match="ML_BAJA_MODEL_SHA256"):
        BajaModel.load(model_path)


def test_load_prod_without_pin_or_checksum_raises(tmp_path, monkeypatch) -> None:
    """En ENV=prod, sin pin ni checksum co-ubicado, load() falla duro."""
    model_path = _save_untrained(tmp_path)
    model_path.with_suffix(".sha256").unlink()
    monkeypatch.setattr(settings, "ML_BAJA_MODEL_SHA256", "")
    monkeypatch.setattr(settings, "ENV", "prod")
    with pytest.raises(RuntimeError, match="Sin verificación de integridad"):
        BajaModel.load(model_path)


def test_load_no_pin_uses_colocated_checksum(tmp_path, monkeypatch) -> None:
    model_path = _save_untrained(tmp_path)
    monkeypatch.setattr(settings, "ML_BAJA_MODEL_SHA256", "")
    assert BajaModel.load(model_path) is not None


# ---------------------------------------------------------------------------
# Codificación de categóricas (techo de cardinalidad de HistGradientBoosting)
# ---------------------------------------------------------------------------


def _fila(cpv4: str, i: int) -> FilaDataset:
    """Fila sintética con todas las FEATURE_COLUMNS pobladas.

    Se construye desde ``FEATURE_COLUMNS`` para que añadir una feature no deje
    este helper a medias: las categóricas necesitan valor sí o sí
    (``_aprender_categorias`` indexa, no usa ``.get``).
    """
    from services.ml.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS

    valores: dict[str, object] = {
        "cpv2": cpv4[:2],
        "cpv4": cpv4,
        "tipo_contrato": "Servicios",
        "ccaa": "Madrid",
        "provincia": "Madrid",
        "organo": "Organo A",
        "fuente": "placsp",
        "banda_importe": "b2",
    }
    features: dict[str, object] = {
        col: valores.get(col, "na") if col in CATEGORICAL_COLUMNS else 1.0
        for col in FEATURE_COLUMNS
    }
    features["log_importe"] = 11.5
    features["mes"] = 1.0
    features["trimestre"] = 1.0
    features["baja_media_organo_cpv4"] = 0.10
    return FilaDataset(licitacion_id=f"L{i}", fecha="2026-01-15", features=features, baja=0.10)


def _filas_cpv4(n: int, frecuentes: int = 0) -> list[FilaDataset]:
    """``n`` códigos CPV-4 distintos; los ``frecuentes`` primeros repiten 3 veces."""
    filas: list[FilaDataset] = []
    for k in range(n):
        for _ in range(3 if k < frecuentes else 1):
            filas.append(_fila(f"{7000 + k:04d}", len(filas)))
    return filas


def test_codificar_no_agrupa_por_debajo_del_techo():
    from services.ml.baja_model import CATEGORIA_OTRAS, _codificar

    _, cats = _codificar(_filas_cpv4(50))

    assert len(cats["cpv4"]) == 50
    assert CATEGORIA_OTRAS not in cats["cpv4"]
    # Orden alfabético estable cuando no hay agrupación.
    assert cats["cpv4"]["7000"] == 0 and cats["cpv4"]["7049"] == 49


def test_codificar_agrupa_la_cola_larga_por_encima_del_techo():
    """Regresión (2026-08): cpv4 llegó a 1061 códigos y el fit reventaba."""
    from services.ml.baja_model import CATEGORIA_OTRAS, MAX_CATEGORIAS, _codificar

    filas = _filas_cpv4(400, frecuentes=MAX_CATEGORIAS - 1)
    _, cats = _codificar(filas)

    assert len(cats["cpv4"]) == MAX_CATEGORIAS
    assert CATEGORIA_OTRAS in cats["cpv4"]
    assert max(cats["cpv4"].values()) == MAX_CATEGORIAS - 1
    # Se conservan los más frecuentes; la cola larga cae en el bucket común.
    assert "7000" in cats["cpv4"] and "7399" not in cats["cpv4"]
    # Las columnas de baja cardinalidad no se tocan.
    assert len(cats["ccaa"]) == 1 and CATEGORIA_OTRAS not in cats["ccaa"]


def test_codificar_manda_valores_no_vistos_al_bucket_otras():
    from services.ml.baja_model import CATEGORIA_OTRAS, MAX_CATEGORIAS, _codificar
    from services.ml.features import FEATURE_COLUMNS

    _, cats = _codificar(_filas_cpv4(400, frecuentes=MAX_CATEGORIAS - 1))
    X, _ = _codificar([_fila("9999", 0)], cats)

    assert X[0, FEATURE_COLUMNS.index("cpv4")] == cats["cpv4"][CATEGORIA_OTRAS]


def test_codificar_modelo_antiguo_sin_bucket_sigue_usando_menos_uno():
    """Un .pkl entrenado antes del bucket no lo tiene en su mapa: -1 (unseen)."""
    from services.ml.baja_model import _codificar
    from services.ml.features import FEATURE_COLUMNS

    cats = {col: {"na": 0} for col in ("cpv2", "tipo_contrato", "ccaa", "fuente", "banda_importe")}
    cats["cpv4"] = {"7000": 0, "7001": 1}

    X, _ = _codificar([_fila("9999", 0)], cats)

    assert X[0, FEATURE_COLUMNS.index("cpv4")] == -1


def test_fit_con_cardinalidad_alta_ya_no_revienta():
    """El fallo real de producción: ValueError('cardinality <= 255') en cada
    pasada de ml_retrain. No ponía el run en rojo (el paso se traga la
    excepción), sólo dejaba el modelo congelado en silencio."""
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingRegressor

    from services.ml.baja_model import _codificar
    from services.ml.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS

    filas = _filas_cpv4(400, frecuentes=254)
    X, _ = _codificar(filas)
    y = np.array([0.10 + (i % 7) * 0.01 for i in range(len(filas))])

    est = HistGradientBoostingRegressor(
        max_iter=5,
        categorical_features=[col in CATEGORICAL_COLUMNS for col in FEATURE_COLUMNS],
        random_state=42,
    )
    est.fit(X, y)

    assert est.predict(X[:1]).shape == (1,)


# ---------------------------------------------------------------------------
# Entrenamiento
# ---------------------------------------------------------------------------


def test_entrenar_sin_datos_suficientes(db):
    resumen = entrenar()
    assert resumen["status"] == "datos_insuficientes"


def test_entrenar_registra_version_y_metricas(db, monkeypatch, tmp_path):
    from db.database import connect
    from db.model_registry import activate_version, get_active, list_versions

    monkeypatch.setattr(baja_model_mod, "MIN_TRAIN_SAMPLES", 40)
    with connect() as c:
        _sembrar_historico(c)

    resumen = entrenar(activar=False, model_path=tmp_path / "baja.pkl")

    assert resumen["status"] == "ok"
    assert resumen["activado"] is False
    for clave in (
        "mae_p50",
        "mae_baseline",
        "mejora_relativa",
        "cobertura_intervalo_80",
        "pinball_p10",
        "pinball_p90",
    ):
        assert clave in resumen

    # Registrada SIN activar (política del RFC: activación manual)
    versiones = list_versions(MODEL_NAME)
    assert len(versiones) == 1 and versiones[0]["is_active"] == 0
    assert get_active(MODEL_NAME) is None

    # Activación manual + rollback (acceptance: rollback probado con get_active)
    assert activate_version(MODEL_NAME, versiones[0]["version"])
    assert get_active(MODEL_NAME)["version"] == versiones[0]["version"]


def test_predicciones_del_modelo_distinguen_segmentos(db, monkeypatch, tmp_path):
    from db.database import connect
    from db.model_registry import activate_version, list_versions

    monkeypatch.setattr(baja_model_mod, "MIN_TRAIN_SAMPLES", 40)
    with connect() as c:
        _sembrar_historico(c)
        _insertar_abierta(c, "AB-A", organo="Organo A")
        _insertar_abierta(c, "AB-B", organo="Organo B")

    entrenar(activar=False, model_path=tmp_path / "baja.pkl")
    activate_version(MODEL_NAME, list_versions(MODEL_NAME)[0]["version"])

    stats = score_predicciones_baja()

    assert stats["serving"] == "modelo"
    pred_a = prediccion_baja("AB-A")
    pred_b = prediccion_baja("AB-B")
    # Órgano A baja ~10%, órgano B ~25%: el modelo debe separarlos
    assert pred_a["p50"] < pred_b["p50"]
    assert pred_a["p10"] <= pred_a["p50"] <= pred_a["p90"]  # monotonicidad
    assert pred_a["model_version"] == 1 and pred_a["computed_at"]  # trazabilidad


# ---------------------------------------------------------------------------
# Scoring batch
# ---------------------------------------------------------------------------


def test_scoring_sin_modelo_sirve_baseline(db):
    from db.database import connect

    with connect() as c:
        _sembrar_historico(c, n_meses=3, por_mes=4)
        _insertar_abierta(c)

    stats = score_predicciones_baja()

    assert stats["serving"] == "baseline"
    pred = prediccion_baja("ABIERTA")
    assert pred is not None
    assert pred["model_version"] is None and pred["serving"] == "baseline"
    assert 0 <= pred["p10"] <= pred["p50"] <= pred["p90"] < 1


def test_scoring_baseline_conformaliza_el_intervalo(db):
    """El baseline servido ensancha su intervalo con la evidencia acumulada.

    Regresión de la degradación observada en producción: el ±40% relativo se
    servía bajo el nombre p10/p90 —que promete un 80%— sin que nadie hubiera
    medido su cobertura. Con pares resueltos suficientes, el offset conformal
    sale de la realidad en vez de la heurística.
    """
    from db.database import connect

    with connect() as c:
        n_hist = _sembrar_historico(c, n_meses=8, por_mes=5)
        # Predicciones que el baseline "sirvio" en su dia (model_version NULL),
        # todas con p50 = 0.10: acierta en Organo A y se queda muy corta en
        # Organo B (baja ~25%), que es lo que genera scores positivos.
        for i in range(n_hist):
            c.execute(
                "INSERT INTO predicciones_baja (licitacion_id, p10, p50, p90, "
                " model_version, computed_at) "
                "VALUES (%s, 0.06, 0.10, 0.14, NULL, CURRENT_TIMESTAMP)",
                (f"H{i}",),
            )
        _insertar_abierta(c)

    stats = score_predicciones_baja()

    assert stats["serving"] == "baseline"
    assert stats["conformal_offset_baseline"] > 0

    pred = prediccion_baja("ABIERTA")
    assert pred["model_version"] is None
    # El contrato de la tabla se mantiene pese al ensanchamiento.
    assert 0 <= pred["p10"] <= pred["p50"] <= pred["p90"] < 1
    # Y el intervalo es mas ancho que el +-40% crudo que se servia antes.
    assert pred["p90"] - pred["p10"] > 0.8 * pred["p50"]


def test_scoring_baseline_sin_pares_resueltos_no_ensancha(db):
    """Sin pares suficientes el offset es 0 y sale la heurística de siempre:
    ensanchar con una muestra de tres pares sería ensanchar por ruido."""
    from db.database import connect

    with connect() as c:
        _sembrar_historico(c, n_meses=3, por_mes=4)
        _insertar_abierta(c)

    stats = score_predicciones_baja()

    assert stats["conformal_offset_baseline"] == 0.0
    pred = prediccion_baja("ABIERTA")
    assert pred["p90"] - pred["p10"] == pytest.approx(0.8 * pred["p50"], rel=1e-3)


def test_media_global_baja_usa_presupuesto_del_lote(db):
    """Regresión: _media_global_baja() comparaba cada adjudicación contra el
    presupuesto del EXPEDIENTE completo, no el de su lote (v65_lotes). Un
    histórico dominado por lotes pequeños con baja real moderada inflaba el
    baseline si se medía contra el presupuesto total del expediente."""
    from db.database import connect
    from services.ml.scoring import _media_global_baja

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, "
            " ccaa, importe, tipo_contrato, fuente, fecha_publicacion, fecha_extraccion) "
            "VALUES ('LOTE-BASE', 'Expediente con lote', 'Organo A', '72000000', "
            " 'Madrid', 100000, 'Servicios', 'placsp', '2025-01-15', CURRENT_TIMESTAMP)"
        )
        lote_id = c.execute(
            "INSERT INTO lotes (licitacion_id, numero, importe, fecha_extraccion) "
            "VALUES ('LOTE-BASE', '1', 20000, CURRENT_TIMESTAMP) RETURNING id"
        ).fetchone()[0]
        c.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
            " fecha_adjudicacion, n_ofertas_recibidas, lote_id, fecha_extraccion) "
            "VALUES ('LOTE-BASE', 'Empresa X', 15000, '2025-02-01', 3, %s, CURRENT_TIMESTAMP)",
            [lote_id],
        )

    # Real baja del lote: (20000-15000)/20000 = 0.25. Contra el expediente
    # completo (100000) habría dado (100000-15000)/100000 = 0.85.
    assert _media_global_baja() == pytest.approx(0.25)


def test_scoring_es_idempotente(db):
    from db.database import connect

    with connect() as c:
        _sembrar_historico(c, n_meses=2, por_mes=4)
        _insertar_abierta(c)

    primera = score_predicciones_baja()
    segunda = score_predicciones_baja()

    assert primera["filas"] == segunda["filas"] == 1
    with connect() as c:
        assert c.execute("SELECT COUNT(*) FROM predicciones_baja").fetchone()[0] == 1


def test_prediccion_inexistente_devuelve_none(db):
    assert prediccion_baja("NO-EXISTE") is None


def test_baseline_intervalo_valido():
    fila = FilaDataset(
        licitacion_id="X",
        fecha="2026-06-01",
        features={"baja_media_organo_cpv4": 0.20},
    )
    pred = predecir_baseline([fila])[0]
    assert pred.p10 == pytest.approx(0.12)
    assert pred.p50 == pytest.approx(0.20)
    assert pred.p90 == pytest.approx(0.28)


# ---------------------------------------------------------------------------
# Conformalización del baseline
# ---------------------------------------------------------------------------


def _pares_simetricos(p50=0.20, n=101, paso=0.004):
    """``(p50, realizada)`` con desviaciones simétricas y deterministas.

    ``n`` impar y centrado en ``p50``: la desviación 0 aparece una vez y cada
    magnitud ``k*paso`` dos, lo que fija el cuantil de los scores sin depender
    de un generador aleatorio.
    """
    mitad = n // 2
    return [(p50, p50 + (i - mitad) * paso) for i in range(n)]


def test_offset_conformal_baseline_alcanza_la_cobertura_nominal():
    """El ±40% relativo no cubre el 80%; el offset es lo que lo consigue.

    Es la regresión de la degradación observada en producción: cobertura real
    del 24% sobre 406 pares contra un nominal del 80%, sirviendo el baseline.
    """
    pares = _pares_simetricos()

    # Sin corregir: el intervalo crudo [0.12, 0.28] deja fuera a la mayoría.
    crudo_lo, crudo_hi = intervalo_baseline(0.20)
    cobertura_cruda = sum(crudo_lo <= y <= crudo_hi for _, y in pares) / len(pares)
    assert cobertura_cruda < 0.45

    offset = offset_conformal_baseline(pares)
    assert offset > 0

    lo, hi = intervalo_baseline(0.20, offset)
    cobertura = sum(lo <= y <= hi for _, y in pares) / len(pares)
    # Split-conformal garantiza >= la nominal, y no de largo: si se pasara
    # mucho, el intervalo sería inútil de puro ancho.
    assert 0.80 <= cobertura <= 0.87


def test_offset_conformal_baseline_se_mide_sobre_el_intervalo_crudo():
    """Idempotencia: recalcular el offset no lo acumula sobre sí mismo.

    El score se calcula reconstruyendo el intervalo desde ``p50`` (que el
    offset nunca toca), no desde el ``p10``/``p90`` almacenados. Si se midiera
    sobre lo guardado —ya ensanchado— la segunda pasada daría ~0 y la anchura
    quedaría congelada en la de la primera.
    """
    pares = _pares_simetricos()
    primero = offset_conformal_baseline(pares)
    # Segunda noche: los mismos pares, ya servidos con el offset aplicado. La
    # entrada de la función es (p50, realizada), así que el resultado no puede
    # depender de lo que se guardó.
    assert offset_conformal_baseline(pares) == pytest.approx(primero)


def test_offset_conformal_baseline_sin_muestra_no_corrige():
    """Con pocos pares la corrección sería ruido: ensanchar por ruido engaña
    tanto como no ensanchar."""
    assert offset_conformal_baseline(_pares_simetricos(n=29)) == 0.0
    assert offset_conformal_baseline([]) == 0.0


def test_intervalo_baseline_conserva_la_monotonia_con_offset_negativo():
    """Un offset negativo estrecha (el intervalo sobraba de ancho) pero nunca
    puede cruzar los extremos: p10 <= p50 <= p90 es contrato de la tabla."""
    lo, hi = intervalo_baseline(0.20, offset=-0.5)
    assert lo <= 0.20 <= hi
    lo, hi = intervalo_baseline(0.20, offset=-0.02)
    assert lo == pytest.approx(0.14) and hi == pytest.approx(0.26)


def _cobertura(pares, offset):
    dentro = 0
    for p50, y in pares:
        lo, hi = intervalo_baseline(p50, offset)
        dentro += lo <= y <= hi
    return dentro / len(pares)


def test_offset_conformal_baseline_cuenta_el_clip_en_cero():
    """El score ignora los pares que ningún offset puede capturar.

    ``intervalo_baseline`` clipa ``p10`` a 0, pero la baja realizada puede ser
    negativa (sobrecoste). Tratar esos pares como "capturables ensanchando"
    corta el cuantil demasiado pronto y la cobertura servida aterriza por
    debajo de la nominal — justo el fallo que este offset viene a evitar.

    Los sobrecostes se siembran sobre expedientes de ``p50`` pequeño: su score
    ingenuo es pequeño también, así que se cuelan en la parte baja del cuantil
    y lo arrastran. Con sobrecostes de score grande el error no se ve, que es
    por lo que pasó desapercibido.
    """
    import numpy as np

    from services.ml.baja_model import _offset_conformal

    pares = [(0.05, -0.005)] * 20
    pares += [(0.20, 0.20 + k * 0.005) for k in range(-40, 40)]

    crudos = [intervalo_baseline(p50) for p50, _ in pares]
    ingenuo = _offset_conformal(
        np.array([c[0] for c in crudos]),
        np.array([c[1] for c in crudos]),
        np.array([y for _, y in pares]),
    )
    corregido = offset_conformal_baseline(pares)

    assert corregido > ingenuo
    assert _cobertura(pares, ingenuo) < 0.80, "el cuantil ingenuo se queda corto"
    assert _cobertura(pares, corregido) >= 0.80


def test_offset_conformal_baseline_no_finge_una_nominal_imposible():
    """Con demasiados sobrecostes el 80% es inalcanzable con ``p10 >= 0``.

    Se sirve el offset más pequeño que captura todo lo capturable —ni un
    infinito, ni un ensanchamiento que no compraría un solo par más— y el hueco
    contra la nominal lo reporta el monitor de calibración.
    """
    import math

    # 40% de sobrecostes: el techo de cobertura es el 60%, bajo la nominal.
    pares = [(0.20, -0.05)] * 40 + [(0.20, 0.20 + k * 0.002) for k in range(-30, 30)]
    offset = offset_conformal_baseline(pares)

    assert math.isfinite(offset)
    assert _cobertura(pares, offset) == pytest.approx(0.60)
    # Y no se infla más allá del techo: ensanchar otro punto no captura nada.
    assert _cobertura(pares, offset + 0.10) == pytest.approx(0.60)


def test_predecir_baseline_aplica_el_offset():
    fila = FilaDataset(
        licitacion_id="X",
        fecha="2026-06-01",
        features={"baja_media_organo_cpv4": 0.20},
    )
    pred = predecir_baseline([fila], offset=0.10)[0]
    assert pred.p50 == pytest.approx(0.20), "la mediana no se toca"
    assert pred.p10 == pytest.approx(0.02)
    assert pred.p90 == pytest.approx(0.38)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Target agregado por expediente (db/repositories/ml_dataset.py)
# ---------------------------------------------------------------------------


def _insertar_expediente(c, lic_id, importe, fecha="2025-03-01", organo="Organo A"):
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
        " importe, tipo_contrato, fuente, fecha_publicacion, fecha_extraccion) "
        "VALUES (%s, 'Expediente', %s, '72000000', 'Madrid', %s, 'Servicios', 'placsp', "
        " %s, CURRENT_TIMESTAMP)",
        (lic_id, organo, importe, fecha),
    )


def _insertar_lote(c, lic_id, numero, importe):
    return c.execute(
        "INSERT INTO lotes (licitacion_id, numero, importe, fecha_extraccion) "
        "VALUES (%s, %s, %s, CURRENT_TIMESTAMP) RETURNING id",
        (lic_id, numero, importe),
    ).fetchone()[0]


def _insertar_adjudicacion(
    c, lic_id, importe, fecha="2025-06-01", lote_id=None, nombre="Empresa X"
):
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
        " fecha_adjudicacion, n_ofertas_recibidas, lote_id, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s, 3, %s, CURRENT_TIMESTAMP)",
        (lic_id, nombre, importe, fecha, lote_id),
    )


def _target(lic_id):
    from services.ml.features import construir_dataset_baja

    filas, _ = construir_dataset_baja()
    por_id = {f.licitacion_id: f for f in filas}
    assert lic_id in por_id, f"{lic_id} no entró en el dataset"
    return por_id[lic_id].baja


def test_target_agregado_suma_solo_los_lotes_adjudicados(db):
    """Expediente de 3 lotes con 2 adjudicados: el denominador son esos 2.

    Contra el presupuesto del expediente (100k) la baja saldría 0.61; contra la
    suma de los lotes adjudicados (50k) es 0.22, que es la baja real de la
    porción adjudicada.
    """
    from db.database import connect

    with connect() as c:
        _insertar_expediente(c, "MULTI", 100_000)
        lote1 = _insertar_lote(c, "MULTI", "1", 20_000)
        lote2 = _insertar_lote(c, "MULTI", "2", 30_000)
        _insertar_lote(c, "MULTI", "3", 50_000)  # publicado, no adjudicado
        _insertar_adjudicacion(c, "MULTI", 15_000, lote_id=lote1)
        _insertar_adjudicacion(c, "MULTI", 24_000, lote_id=lote2)

    assert _target("MULTI") == pytest.approx(1 - 39_000 / 50_000)


def test_target_agregado_sin_lote_resuelto_cae_al_expediente(db):
    """Datos anteriores a v65_lotes: sin lote_id, el denominador es l.importe."""
    from db.database import connect

    with connect() as c:
        _insertar_expediente(c, "PRE-V65", 100_000)
        _insertar_adjudicacion(c, "PRE-V65", 40_000)
        _insertar_adjudicacion(c, "PRE-V65", 35_000)

    assert _target("PRE-V65") == pytest.approx(1 - 75_000 / 100_000)


def test_lote_compartido_no_cuenta_su_presupuesto_dos_veces(db):
    """Dos empresas ganan el MISMO lote: su presupuesto entra una sola vez.

    Sumando por fila de adjudicación el denominador sería 40k y la baja 0.575;
    con los lotes distintos es 20k y la baja 0.15.
    """
    from db.database import connect

    with connect() as c:
        _insertar_expediente(c, "COMPARTIDO", 100_000)
        lote = _insertar_lote(c, "COMPARTIDO", "1", 20_000)
        _insertar_adjudicacion(c, "COMPARTIDO", 8_000, lote_id=lote, nombre="Empresa A")
        _insertar_adjudicacion(c, "COMPARTIDO", 9_000, lote_id=lote, nombre="Empresa B")

    assert _target("COMPARTIDO") == pytest.approx(1 - 17_000 / 20_000)


def test_una_fila_por_expediente_no_una_por_lote(db):
    from db.database import connect
    from services.ml.features import construir_dataset_baja

    with connect() as c:
        _insertar_expediente(c, "UNICA", 100_000)
        lote1 = _insertar_lote(c, "UNICA", "1", 40_000)
        lote2 = _insertar_lote(c, "UNICA", "2", 60_000)
        _insertar_adjudicacion(c, "UNICA", 30_000, lote_id=lote1)
        _insertar_adjudicacion(c, "UNICA", 50_000, lote_id=lote2)

    filas, _ = construir_dataset_baja()
    assert [f.licitacion_id for f in filas].count("UNICA") == 1


# ---------------------------------------------------------------------------
# Anti-fuga: el ancla es la publicación, no la adjudicación
# ---------------------------------------------------------------------------


def test_no_ve_adjudicaciones_posteriores_a_su_publicacion(db):
    """Una adjudicación entre la publicación y la adjudicación de una fila
    NO puede entrar en sus agregados históricos.

    Con el ancla anterior (fecha de adjudicación) la fila X sí veía a Y, que se
    resolvió cuatro meses después de publicarse X: meses de información que en
    scoring no existen, porque ahí la licitación aún está abierta.
    """
    from db.database import connect

    with connect() as c:
        # Z se resuelve antes de que X se publique: X sí debe verla.
        _insertar_expediente(c, "Z", 100_000, fecha="2024-06-01")
        _insertar_adjudicacion(c, "Z", 90_000, fecha="2024-08-01")  # baja 0.10
        # Y se resuelve DESPUÉS de que X se publique: X no debe verla.
        _insertar_expediente(c, "Y", 100_000, fecha="2024-12-01")
        _insertar_adjudicacion(c, "Y", 50_000, fecha="2025-03-01")  # baja 0.50
        _insertar_expediente(c, "X", 100_000, fecha="2025-01-01")
        _insertar_adjudicacion(c, "X", 80_000, fecha="2025-06-01")  # baja 0.20

    from services.ml.features import construir_dataset_baja

    filas, _ = construir_dataset_baja()
    x = next(f for f in filas if f.licitacion_id == "X")

    # Solo Z está incorporada, así que la media del órgano (y el prior global,
    # que también es 0.10) valen 0.10. Si Y se hubiera colado, ambas serían 0.30.
    assert x.features["baja_media_organo"] == pytest.approx(0.10)
    assert x.features["n_obs_organo"] == pytest.approx(1.0)


def test_scoring_y_entrenamiento_comparten_las_columnas(db):
    """Ninguna feature puede existir al entrenar y faltar al servir.

    Es la asimetría que tenía ``n_ofertas``: presente en el 100% de las filas
    de entrenamiento (venía de ``adjudicaciones``) y ausente en el 100% de las
    de scoring, sin que el monitor de drift pudiera verlo.
    """
    from db.database import connect
    from services.ml.features import (
        CATEGORICAL_COLUMNS,
        FEATURE_COLUMNS,
        construir_dataset_baja,
        features_licitaciones_abiertas,
    )

    with connect() as c:
        _sembrar_historico(c, n_meses=6, por_mes=6)
        _insertar_abierta(c)

    entrenamiento, _ = construir_dataset_baja()
    scoring = features_licitaciones_abiertas()
    assert entrenamiento and scoring
    numericas = FEATURE_COLUMNS[len(CATEGORICAL_COLUMNS) :]

    def _cobertura(filas, col):
        return sum(1 for f in filas if f.features.get(col) is not None) / len(filas)

    ausentes = [
        col
        for col in numericas
        if _cobertura(entrenamiento, col) > 0.5 and _cobertura(scoring, col) == 0.0
    ]
    assert not ausentes, f"features disponibles al entrenar y nunca al servir: {ausentes}"
    assert "n_ofertas" not in FEATURE_COLUMNS


# ---------------------------------------------------------------------------
# Guard de layout de features y degradación del serving
# ---------------------------------------------------------------------------


def test_predict_rechaza_un_artefacto_con_otro_layout():
    from services.ml.baja_model import FeatureSchemaMismatch

    modelo = BajaModel(
        modelos={},
        categorias={},
        metadata={"feature_columns": ["cpv2", "n_ofertas"]},  # layout viejo
    )
    with pytest.raises(FeatureSchemaMismatch, match="otras columnas"):
        modelo.predict([_fila("7200", 0)])


def test_predict_rechaza_un_artefacto_sin_feature_columns():
    """Falla cerrado: sin metadata no se puede verificar el layout."""
    from services.ml.baja_model import FeatureSchemaMismatch

    modelo = BajaModel(modelos={}, categorias={}, metadata={})
    with pytest.raises(FeatureSchemaMismatch, match="no registra feature_columns"):
        modelo.predict([_fila("7200", 0)])


def test_scoring_degrada_a_baseline_si_el_layout_no_coincide(db, monkeypatch, tmp_path):
    """El .pkl activo entrenado con otras columnas no debe servirse.

    Es el escenario real de un despliegue en el que el artefacto activo es
    anterior al cambio de features: sin el guard, sus árboles reciben columnas
    distintas en las mismas posiciones y devuelven números sin significado.
    """
    from db.database import connect
    from db.model_registry import activate_version, list_versions

    monkeypatch.setattr(baja_model_mod, "MIN_TRAIN_SAMPLES", 40)
    with connect() as c:
        _sembrar_historico(c)
        _insertar_abierta(c)

    model_path = tmp_path / "baja.pkl"
    entrenar(activar=False, model_path=model_path)
    activate_version(MODEL_NAME, list_versions(MODEL_NAME)[0]["version"])

    # Se manipula la metadata del artefacto para simular un layout anterior.
    modelo = BajaModel.load(model_path)
    modelo.metadata["feature_columns"] = ["cpv2", "n_ofertas"]
    modelo.save(model_path)
    monkeypatch.setattr(
        "shared.model_artifacts.resolve_active_artifact", lambda *_a, **_k: model_path
    )

    stats = score_predicciones_baja()

    assert stats["serving"] == "baseline"
    # `degradado` distingue este baseline (hay modelo activo que no se pudo
    # servir) del baseline honesto por no haber modelo: el CLI del workflow
    # pone el job en rojo solo en el primero.
    assert stats["degradado"] == "feature_schema_mismatch"
    assert prediccion_baja("ABIERTA")["model_version"] is None


def test_scoring_marca_degradado_si_el_artefacto_no_resuelve(db, monkeypatch):
    """Versión activa cuyo .pkl no existe ni se puede descargar de la Release.

    Es el estado en el que quedaba cualquier versión entrenada en un runner
    efímero antes de que `train-predictivos.yml` publicara los artefactos.
    """
    from db.database import connect
    from db.model_registry import register_version

    with connect() as c:
        _sembrar_historico(c, n_meses=2, por_mes=4)
        _insertar_abierta(c)

    register_version(name=MODEL_NAME, path="data/models/no-existe.pkl", sha256="", activate=True)
    monkeypatch.setattr("shared.model_artifacts.resolve_active_artifact", lambda *_a, **_k: None)

    stats = score_predicciones_baja()

    assert stats["serving"] == "baseline"
    assert stats["degradado"] == "artefacto_irresoluble"


def test_scoring_sin_modelo_activo_no_marca_degradado(db):
    """Baseline sin versión activa: contrato del RFC, no una avería."""
    from db.database import connect

    with connect() as c:
        _sembrar_historico(c, n_meses=2, por_mes=4)
        _insertar_abierta(c)

    stats = score_predicciones_baja()

    assert stats["serving"] == "baseline"
    assert stats["degradado"] is None


# ---------------------------------------------------------------------------
# Conformal (split-CQR) y monitor de nulos
# ---------------------------------------------------------------------------


def test_offset_conformal_lleva_la_cobertura_al_objetivo():
    """Un intervalo demasiado estrecho se ensancha hasta cubrir el 80%."""
    import numpy as np

    from services.ml.baja_model import _offset_conformal

    rng = np.random.default_rng(42)
    y = rng.uniform(0.0, 0.5, 400)
    centro = np.full(400, 0.25)
    p10, p90 = centro - 0.02, centro + 0.02  # cubre muy poco

    offset = _offset_conformal(p10, p90, y)
    cobertura = float(np.mean((y >= p10 - offset) & (y <= p90 + offset)))

    assert offset > 0
    assert cobertura == pytest.approx(0.80, abs=0.05)


def test_offset_conformal_estrecha_un_intervalo_que_sobra():
    """Simétrico: si el intervalo cubre de más, el offset es negativo.

    Es lo que hace que la cobertura aterrice EN el objetivo en vez de limitarse
    a superarlo, que es la diferencia entre un intervalo informativo y uno
    inútilmente ancho.
    """
    import numpy as np

    from services.ml.baja_model import _offset_conformal

    y = np.full(200, 0.25)
    p10, p90 = np.full(200, 0.0), np.full(200, 0.9)  # cubre el 100%

    assert _offset_conformal(p10, p90, y) < 0


def _fila_drift(fecha, **numericas):
    """Fila sintética con el layout canónico y las numéricas que interesen."""
    import services.ml.features as features_mod

    base = dict.fromkeys(features_mod.FEATURE_COLUMNS, 1.0)
    base.update({c: "x" for c in features_mod.CATEGORICAL_COLUMNS})
    base["mes"] = float(int(fecha[5:7]))
    base["trimestre"] = float((int(fecha[5:7]) - 1) // 3 + 1)
    base.update(numericas)
    return FilaDataset(licitacion_id="L", fecha=fecha, features=base)


def _historico_con_rampa(n=3000):
    """Serie 2022-01 → 2026-08 con la forma real del dataset de entrenamiento.

    Los ``n_obs`` arrancan en cero y se llenan según se acumula histórico, y
    ``baja_media_organo`` --que sí gobierna la severidad-- sube con ellos
    porque al principio de la serie no hay observaciones que promediar.
    ``log_importe`` es estacionario. Es la asimetría que hacía que el monitor
    comparase la rampa de arranque contra un scoring siempre "caliente".
    """
    filas = []
    for i in range(n):
        mes_abs = i * 55 // n
        filas.append(
            _fila_drift(
                f"{2022 + mes_abs // 12}-{mes_abs % 12 + 1:02d}-15",
                n_obs_organo=float(i * 200 // n),
                n_obs_cpv4=float(i * 400 // n),
                n_obs_organo_cpv4=float(i * 100 // n),
                baja_media_organo=0.100 + (i / n) * 0.050,
                log_importe=11.0 + (i % 40) * 0.05,
            )
        )
    return filas


def _abiertas_del_tramo_reciente(n=500, **numericas):
    """Scoring sacado de la MISMA distribución que el tramo reciente del histórico."""
    filas = []
    for i in range(n):
        campos = {
            "n_obs_organo": float(174 + i % 26),
            "n_obs_cpv4": float(348 + i % 52),
            "n_obs_organo_cpv4": float(87 + i % 13),
            # Mismo rango que el tramo reciente del histórico (i/n desde 0.873).
            "baja_media_organo": 0.1437 + (i / n) * 0.0063,
            "log_importe": 11.0 + (i % 40) * 0.05,
        }
        campos.update(numericas)
        filas.append(_fila_drift(f"2026-{i * 8 // n + 1:02d}-10", **campos))
    return filas


def _drift_de(monkeypatch, entrenamiento, scoring):
    import observability.alerts as alerts_mod
    import services.ml.features as features_mod
    from services.ml.drift import comprobar_drift_baja

    # El canal de alertas es real y en severidad != ok intenta mandar email:
    # sin esto cada test que alerta se come el timeout de SMTP.
    monkeypatch.setattr(alerts_mod, "notify", lambda *a, **k: None)
    monkeypatch.setattr(features_mod, "construir_dataset_baja", lambda: (entrenamiento, None))
    monkeypatch.setattr(features_mod, "features_licitaciones_abiertas", lambda: scoring)
    return comprobar_drift_baja()


def test_drift_ve_una_feature_ausente_en_scoring(monkeypatch):
    """El caso que reportaba PSI 0.00 "estable": ausente al servir, presente al
    entrenar. El PSI solo compara los presentes; el delta de nulos lo caza."""
    entrenamiento = [_fila_drift("2026-01-01") for _ in range(50)]
    scoring = [_fila_drift("2026-01-01", log_importe=None) for _ in range(50)]

    resultado = _drift_de(monkeypatch, entrenamiento, scoring)

    assert resultado["status"] == "crit"
    assert resultado["missing_delta"]["log_importe"] == pytest.approx(1.0)
    # 50 filas no dan ventana de referencia utilizable: se cae al histórico
    # completo y el resultado lo dice en vez de comparar contra cuatro filas.
    assert resultado["ventana_ref"] is None


def test_drift_no_alerta_por_la_rampa_de_arranque_del_historico(monkeypatch):
    """Sin deriva real, el monitor calla.

    El scoring sale de la misma distribución que el tramo reciente del
    histórico: lo único que separa a los dos conjuntos es que el entrenamiento
    también cubre el arranque de la serie, con los acumuladores a medio llenar.
    Eso no es deriva y no debe alertar.
    """
    resultado = _drift_de(monkeypatch, _historico_con_rampa(), _abiertas_del_tramo_reciente())

    assert resultado["status"] == "ok"
    assert resultado["ventana_ref"] is not None
    assert resultado["n_ref"] < 3000
    # Contadores y calendario siguen midiéndose --su PSI sigue siendo alto, y es
    # correcto que lo sea-- pero no gobiernan la severidad.
    assert "n_obs_organo" in resultado["psi_informativo"]
    assert "mes" in resultado["psi_informativo"]
    assert "n_obs_organo" not in resultado["psi"]


def test_drift_con_historico_completo_alertaria_por_la_rampa(monkeypatch):
    """Contraprueba de la anterior: el mismo dato, sin acotar la referencia.

    Es el falso positivo que se reportaba en producción --PSI de 5-6 en todas
    las features de acumulador, todas las noches, sin nada que arreglar--.
    """
    import services.ml.drift as drift_mod

    monkeypatch.setattr(drift_mod, "_MIN_REF_VENTANA", 10**9)  # fuerza el fallback

    resultado = _drift_de(monkeypatch, _historico_con_rampa(), _abiertas_del_tramo_reciente())

    assert resultado["status"] == "crit"
    assert resultado["ventana_ref"] is None


def test_drift_ve_una_deriva_real_dentro_de_la_ventana(monkeypatch):
    """Acotar la referencia no ciega el monitor: una feature estática que se
    desplaza fuera del rango de entrenamiento sigue siendo crit."""
    resultado = _drift_de(
        monkeypatch,
        _historico_con_rampa(),
        _abiertas_del_tramo_reciente(log_importe=14.0),
    )

    assert resultado["status"] == "crit"
    assert resultado["psi_peor_feature"] == "log_importe"
    assert resultado["bins_vacios"]["log_importe"] > 0


def test_drift_alerta_si_el_historico_acumulado_se_desploma(monkeypatch):
    """La dirección en la que un contador SÍ puede ir mal.

    Que ``n_obs`` suba es el sistema acumulando histórico. Que se hunda es la
    ingesta rota o el dedupe llevándose media serie, y eso el PSI no lo
    distingue de lo primero: lo caza el cociente de medianas.
    """
    resultado = _drift_de(
        monkeypatch,
        _historico_con_rampa(),
        _abiertas_del_tramo_reciente(n_obs_organo=2.0, n_obs_cpv4=2.0, n_obs_organo_cpv4=1.0),
    )

    assert resultado["status"] == "crit"
    assert resultado["contadores"]["n_obs_organo"]["ratio"] < 0.25


def test_api_prediccion_baja(client, auth):
    from db.database import connect

    with connect() as c:
        _sembrar_historico(c, n_meses=2, por_mes=4)
        _insertar_abierta(c)
    score_predicciones_baja()

    resp = client.get("/api/v1/licitaciones/ABIERTA/prediccion-baja", headers=auth)

    assert resp.status_code == 200
    data = resp.json()
    assert {"p10", "p50", "p90", "model_version", "computed_at", "serving"} <= set(data)

    assert client.get("/api/v1/licitaciones/NADA/prediccion-baja", headers=auth).status_code == 404


# ---------------------------------------------------------------------------
# La baja real que sirve el API usa el denominador del entrenamiento
# ---------------------------------------------------------------------------


def test_baja_real_usa_el_presupuesto_efectivo_del_expediente(db):
    """Regresión: ``_baja_real`` dividía entre ``licitaciones.importe``.

    El modelo entrena —y ``calibration.py`` mide— contra el presupuesto
    efectivo (``db/repositories/ml_dataset.py``): la suma de los lotes
    adjudicados cuando todos están resueltos. Con el denominador anterior este
    expediente devolvía por el API una "baja real" del 61% al lado de un
    intervalo entrenado contra el 22%, y la comparación estimado-vs-real que
    justifica el endpoint enfrentaba dos magnitudes distintas.
    """
    from db.database import connect

    with connect() as c:
        _insertar_expediente(c, "MULTI-REAL", 100_000)
        lote1 = _insertar_lote(c, "MULTI-REAL", "1", 20_000)
        lote2 = _insertar_lote(c, "MULTI-REAL", "2", 30_000)
        _insertar_lote(c, "MULTI-REAL", "3", 50_000)  # publicado, no adjudicado
        _insertar_adjudicacion(c, "MULTI-REAL", 15_000, lote_id=lote1)
        _insertar_adjudicacion(c, "MULTI-REAL", 24_000, lote_id=lote2)

    datos = prediccion_baja("MULTI-REAL")

    assert datos is not None
    assert datos["baja_real"] == pytest.approx(1 - 39_000 / 50_000)
    assert datos["importe_adjudicado"] == pytest.approx(39_000)
    # El invariante, no el número: la misma magnitud que aprende el modelo.
    assert datos["baja_real"] == pytest.approx(_target("MULTI-REAL"))


def test_baja_real_no_cuenta_dos_veces_el_lote_compartido(db):
    """Dos empresas ganan el mismo lote: su presupuesto entra una sola vez."""
    from db.database import connect

    with connect() as c:
        _insertar_expediente(c, "COMPARTIDO-REAL", 100_000)
        lote = _insertar_lote(c, "COMPARTIDO-REAL", "1", 20_000)
        _insertar_adjudicacion(c, "COMPARTIDO-REAL", 8_000, lote_id=lote, nombre="Empresa A")
        _insertar_adjudicacion(c, "COMPARTIDO-REAL", 9_000, lote_id=lote, nombre="Empresa B")

    datos = prediccion_baja("COMPARTIDO-REAL")

    assert datos is not None
    assert datos["baja_real"] == pytest.approx(1 - 17_000 / 20_000)
    assert datos["baja_real"] == pytest.approx(_target("COMPARTIDO-REAL"))


def test_baja_real_sin_lote_resuelto_cae_al_presupuesto_del_expediente(db):
    """Datos anteriores a v65_lotes: el denominador vuelve a ser ``l.importe``."""
    from db.database import connect

    with connect() as c:
        _insertar_expediente(c, "PRE-V65-REAL", 100_000)
        _insertar_adjudicacion(c, "PRE-V65-REAL", 40_000)
        _insertar_adjudicacion(c, "PRE-V65-REAL", 35_000)

    datos = prediccion_baja("PRE-V65-REAL")

    assert datos is not None
    assert datos["baja_real"] == pytest.approx(1 - 75_000 / 100_000)
    assert datos["baja_real"] == pytest.approx(_target("PRE-V65-REAL"))


# ---------------------------------------------------------------------------
# Rolling-origin: los folds se cortan por la fecha en que la baja es observable
# ---------------------------------------------------------------------------


def _dataset_publicacion_vs_adjudicacion(
    *, meses: int = 48, por_mes: int = 10, retardo_meses: int = 8
) -> tuple[list[FilaDataset], dict[str, str]]:
    """Filas publicadas mes a mes y adjudicadas ``retardo_meses`` después.

    El retardo entre publicación y adjudicación es lo que separa los dos
    criterios de corte: con folds cortados por publicación, el train de cada
    fold se lleva todas las filas de los últimos ``retardo_meses`` antes del
    corte, cuya baja todavía no existía en ese instante.
    """
    from datetime import datetime

    def _fecha(indice: int) -> str:
        return datetime(2021 + indice // 12, indice % 12 + 1, 15).strftime("%Y-%m-%d")

    filas: list[FilaDataset] = []
    fechas_label: dict[str, str] = {}
    for mes in range(meses):
        for k in range(por_mes):
            lic_id = f"L{mes:02d}-{k}"
            filas.append(
                FilaDataset(licitacion_id=lic_id, fecha=_fecha(mes), features={}, baja=0.1)
            )
            fechas_label[lic_id] = _fecha(mes + retardo_meses)
    return filas, fechas_label


def test_ningun_fold_entrena_con_etiquetas_posteriores_a_su_corte():
    """El invariante del rolling-origin honesto.

    Antes los folds se cortaban por ``fecha_anchor`` (la publicación) en los dos
    lados. Como el ancla nunca es posterior a la adjudicación, el train recibía
    filas adjudicadas después del corte: etiquetas que en ese instante no
    existían.
    """
    from services.ml.baja_model import _folds_rolling

    filas, fechas_label = _dataset_publicacion_vs_adjudicacion()

    folds = _folds_rolling(filas, 6, 3, fechas_label)

    assert len(folds) == 3
    for train, valid in folds:
        assert train and valid
        corte = min(f.fecha for f in valid)  # origen del fold
        ultima_etiqueta = max(fechas_label[f.licitacion_id] for f in train)
        assert ultima_etiqueta < corte, (
            f"el train conoce una baja de {ultima_etiqueta}, posterior al corte {corte}"
        )
        # Y el test sigue seleccionándose por publicación: es lo que se
        # observa al servir, cuando la licitación aún está abierta.
        assert all(f.fecha >= corte for f in valid)


def test_las_filas_publicadas_pero_no_adjudicadas_quedan_en_la_banda_de_embargo():
    """Ni train ni test en el fold que las pilla a medias.

    Su baja no se conocía en el corte (no pueden entrenar) y ya estaban
    publicadas cuando empieza el bloque de validación (no son test).
    """
    from services.ml.baja_model import _folds_rolling

    filas, fechas_label = _dataset_publicacion_vs_adjudicacion()

    train, valid = _folds_rolling(filas, 6, 3, fechas_label)[0]
    usadas = {f.licitacion_id for f in train} | {f.licitacion_id for f in valid}
    corte = min(f.fecha for f in valid)

    embargadas = [
        f
        for f in filas
        if f.fecha < corte <= fechas_label[f.licitacion_id] and f.licitacion_id not in usadas
    ]
    assert embargadas, "sin banda de embargo el corte no está haciendo nada"
    assert all(f.licitacion_id not in usadas for f in embargadas)


def test_el_split_unico_de_respaldo_tambien_embarga_el_train():
    """El fallback de histórico corto comparte el criterio de los folds."""
    from services.ml.baja_model import _split_temporal

    filas, fechas_label = _dataset_publicacion_vs_adjudicacion(
        meses=12, por_mes=12, retardo_meses=2
    )

    train, valid = _split_temporal(filas, 6, fechas_label)

    assert train and valid
    corte = min(f.fecha for f in valid)
    assert max(fechas_label[f.licitacion_id] for f in train) < corte
