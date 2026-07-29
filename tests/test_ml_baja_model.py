"""Tests del modelo de baja y su scoring batch (Fase 6, RFC 20260611-2)."""

from __future__ import annotations

import hashlib

import pytest

import services.ml.baja_model as baja_model_mod
from config import settings
from services.ml.baja_model import MODEL_NAME, BajaModel, entrenar, predecir_baseline
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
                "VALUES (?, ?, ?, '72000000', 'Madrid', ?, 'Servicios', 'placsp', ?, "
                " CURRENT_TIMESTAMP)",
                (f"H{i}", f"Contrato {i}", organo, importe, fecha),
            )
            c.execute(
                "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
                " fecha_adjudicacion, n_ofertas_recibidas, fecha_extraccion) "
                "VALUES (?, 'Empresa X', ?, ?, 3, CURRENT_TIMESTAMP)",
                (f"H{i}", importe * (1 - baja), fecha),
            )
            i += 1
    return i


def _insertar_abierta(c, lic_id="ABIERTA", organo="Organo A"):
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
        " importe, estado, tipo_contrato, fuente, fecha_publicacion, fecha_extraccion) "
        "VALUES (?, 'Nueva', ?, '72000000', 'Madrid', 300000, 'PUB', 'Servicios', "
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
# API
# ---------------------------------------------------------------------------


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
