"""Tests del etiquetado y modelo de retención (Fase 6.2, RFC 20260611-2)."""

from __future__ import annotations

import hashlib

import pytest

import services.ml.retencion_model as retencion_model_mod
from config import settings
from services.ml.drift import _psi, comprobar_drift_baja
from services.ml.retencion_labels import (
    construir_pares,
    features_para_vencimientos,
    muestra_auditoria,
)
from services.ml.retencion_model import MODEL_NAME, RetencionModel, entrenar
from services.ml.scoring import score_predicciones_retencion


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _empresa(c, nombre):
    row = c.execute(
        "INSERT INTO empresas (nombre_canonico) VALUES (?) RETURNING id", (nombre,)
    ).fetchone()
    return row[0]


def _contrato(
    c,
    lic_id,
    *,
    organo="Organo A",
    cpv="72000000",
    fecha_adj,
    fecha_fin=None,
    empresa_id,
    importe=100_000.0,
    adjudicado=90_000.0,
):
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
        " importe, fecha_fin, fuente, fecha_publicacion, fecha_extraccion) "
        "VALUES (?, ?, ?, ?, 'Madrid', ?, ?, 'placsp', ?, CURRENT_TIMESTAMP)",
        (lic_id, f"Servicio mantenimiento {lic_id}", organo, cpv, importe, fecha_fin, fecha_adj),
    )
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
        " fecha_adjudicacion, empresa_id, fecha_extraccion) "
        "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (lic_id, f"Empresa {empresa_id}", adjudicado, fecha_adj, empresa_id),
    )


# ---------------------------------------------------------------------------
# Integridad del modelo serializado (pin out-of-band + checksum co-ubicado)
# ---------------------------------------------------------------------------


def _save_untrained(tmp_path):
    modelo = RetencionModel(clf=None, metadata={})
    model_path = tmp_path / "ret.pkl"
    modelo.save(model_path)  # escribe .pkl + .sha256 co-ubicado
    return model_path


def test_load_rejects_when_pin_mismatch(tmp_path, monkeypatch) -> None:
    model_path = _save_untrained(tmp_path)
    monkeypatch.setattr(settings, "ML_RETENCION_MODEL_SHA256", "de" * 32)  # no coincide
    with pytest.raises(RuntimeError, match="ML_RETENCION_MODEL_SHA256"):
        RetencionModel.load(model_path)


def test_load_accepts_when_pin_matches(tmp_path, monkeypatch) -> None:
    model_path = _save_untrained(tmp_path)
    correct = hashlib.sha256(model_path.read_bytes()).hexdigest()
    monkeypatch.setattr(settings, "ML_RETENCION_MODEL_SHA256", correct)
    assert RetencionModel.load(model_path) is not None


def test_load_pin_detects_tampered_model(tmp_path, monkeypatch) -> None:
    """Pin del modelo original; luego se manipula el .pkl y su .sha256
    co-ubicado (simula un release comprometido). El pin debe detectarlo."""
    model_path = _save_untrained(tmp_path)
    original_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    monkeypatch.setattr(settings, "ML_RETENCION_MODEL_SHA256", original_hash)

    model_path.write_bytes(b"contenido manipulado")
    tampered_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    model_path.with_suffix(".sha256").write_text(tampered_hash, encoding="utf-8")

    with pytest.raises(RuntimeError, match="ML_RETENCION_MODEL_SHA256"):
        RetencionModel.load(model_path)


def test_load_prod_without_pin_or_checksum_raises(tmp_path, monkeypatch) -> None:
    """En ENV=prod, sin pin ni checksum co-ubicado, load() falla duro."""
    model_path = _save_untrained(tmp_path)
    model_path.with_suffix(".sha256").unlink()
    monkeypatch.setattr(settings, "ML_RETENCION_MODEL_SHA256", "")
    monkeypatch.setattr(settings, "ENV", "prod")
    with pytest.raises(RuntimeError, match="Sin verificación de integridad"):
        RetencionModel.load(model_path)


def test_load_no_pin_uses_colocated_checksum(tmp_path, monkeypatch) -> None:
    model_path = _save_untrained(tmp_path)
    monkeypatch.setattr(settings, "ML_RETENCION_MODEL_SHA256", "")
    assert RetencionModel.load(model_path) is not None


# ---------------------------------------------------------------------------
# Etiquetado vencimiento→sucesor
# ---------------------------------------------------------------------------


def test_par_retenido_y_perdido(db):
    from db.database import connect

    with connect() as c:
        incumbente = _empresa(c, "Incumbente SL")
        rival = _empresa(c, "Rival SA")
        # Contrato 1 vence 2025-06; lo renueva el mismo → label 1
        _contrato(c, "C1", fecha_adj="2023-06-01", fecha_fin="2025-06-01", empresa_id=incumbente)
        _contrato(c, "C1-SIG", fecha_adj="2025-07-01", empresa_id=incumbente)
        # Contrato 2 (otro órgano) vence 2025-09; lo gana otro → label 0
        _contrato(
            c,
            "C2",
            organo="Organo B",
            fecha_adj="2023-09-01",
            fecha_fin="2025-09-01",
            empresa_id=incumbente,
        )
        _contrato(c, "C2-SIG", organo="Organo B", fecha_adj="2025-10-01", empresa_id=rival)

    pares = construir_pares()

    por_id = {p.licitacion_id: p for p in pares}
    assert por_id["C1"].label == 1 and por_id["C1"].sucesor_id == "C1-SIG"
    assert por_id["C2"].label == 0 and por_id["C2"].sucesor_id == "C2-SIG"
    # El sucesor de C1 no genera par propio sin un tercero posterior… pero si
    # lo genera, nunca debe emparejarse consigo mismo
    for p in pares:
        assert p.sucesor_id != p.licitacion_id


def test_sin_sucesor_en_ventana_no_genera_par(db):
    from db.database import connect

    with connect() as c:
        e1 = _empresa(c, "Solitaria SL")
        _contrato(c, "C1", fecha_adj="2020-01-01", fecha_fin="2021-01-01", empresa_id=e1)
        # Siguiente análogo 4 años después: fuera de la ventana de ±18 meses
        _contrato(c, "C2", fecha_adj="2025-01-01", empresa_id=e1)

    assert construir_pares() == []


def test_features_anti_fuga_y_auditoria(db):
    from db.database import connect

    with connect() as c:
        e1 = _empresa(c, "Veterana SL")
        _contrato(c, "OLD", fecha_adj="2022-01-01", empresa_id=e1)  # relación previa
        _contrato(
            c,
            "C1",
            fecha_adj="2023-06-01",
            fecha_fin="2025-06-01",
            empresa_id=e1,
            importe=100_000.0,
            adjudicado=80_000.0,
        )
        _contrato(c, "C1-SIG", fecha_adj="2025-07-01", empresa_id=e1)

    pares = construir_pares()
    par = next(p for p in pares if p.licitacion_id == "C1")

    # 2 contratos previos al vencimiento (OLD y el propio C1)
    assert par.features["contratos_previos_organo"] == 2.0
    assert par.features["antiguedad_relacion_meses"] == pytest.approx(41, abs=2)
    assert par.features["baja_original"] == pytest.approx(0.20)
    assert par.features["cuota_segmento"] == pytest.approx(1.0)  # monopolio

    muestra = muestra_auditoria(10)
    assert muestra and {"original", "sucesor", "label", "empresa_original"} <= set(muestra[0])


def test_features_para_vencimientos_solo_futuros(db):
    from db.database import connect

    with connect() as c:
        e1 = _empresa(c, "Activa SL")
        _contrato(c, "PASADO", fecha_adj="2020-01-01", fecha_fin="2021-01-01", empresa_id=e1)
        _contrato(c, "PROXIMO", fecha_adj="2024-01-01", fecha_fin="2026-09-01", empresa_id=e1)
        _contrato(c, "LEJANO", fecha_adj="2024-01-01", fecha_fin="2030-01-01", empresa_id=e1)

    filas = features_para_vencimientos(months_ahead=12)

    assert [f.licitacion_id for f in filas] == ["PROXIMO"]
    assert filas[0].label == -1


# ---------------------------------------------------------------------------
# Modelo + scoring
# ---------------------------------------------------------------------------


def _sembrar_pares(c, n=120):
    """Histórico sintético: la empresa 'fiel' retiene, la 'fragil' pierde."""
    fiel = _empresa(c, "Fiel SL")
    fragil = _empresa(c, "Fragil SL")
    rival = _empresa(c, "Rival SA")
    for i in range(n):
        yyyy, mm = divmod(i, 12)
        adj = f"{2020 + yyyy}-{mm + 1:02d}-01"
        fin = f"{2022 + yyyy}-{mm + 1:02d}-01"
        sig = f"{2022 + yyyy}-{mm + 1:02d}-20"
        if i % 2 == 0:
            organo = f"Organo F{i % 7}"
            _contrato(
                c,
                f"F{i}",
                organo=organo,
                fecha_adj=adj,
                fecha_fin=fin,
                empresa_id=fiel,
                adjudicado=92_000.0,
            )
            _contrato(c, f"F{i}-SIG", organo=organo, fecha_adj=sig, empresa_id=fiel)
        else:
            organo = f"Organo G{i % 7}"
            _contrato(
                c,
                f"G{i}",
                organo=organo,
                fecha_adj=adj,
                fecha_fin=fin,
                empresa_id=fragil,
                adjudicado=70_000.0,
            )
            _contrato(c, f"G{i}-SIG", organo=organo, fecha_adj=sig, empresa_id=rival)
    return fiel, fragil


def test_entrenar_sin_datos(db):
    assert entrenar()["status"] == "datos_insuficientes"


def test_entrenar_y_puntuar_retencion(db, monkeypatch, tmp_path):
    from db.database import connect
    from db.model_registry import activate_version, list_versions

    monkeypatch.setattr(retencion_model_mod, "MIN_TRAIN_SAMPLES", 60)
    with connect() as c:
        fiel, _ = _sembrar_pares(c)
        # Vencimiento futuro del incumbente fiel para el scoring
        _contrato(
            c,
            "FUTURO",
            organo="Organo F1",
            fecha_adj="2025-09-01",
            fecha_fin="2026-10-01",
            empresa_id=fiel,
            adjudicado=92_000.0,
        )

    resumen = entrenar(activar=False, model_path=tmp_path / "ret.pkl")

    assert resumen["status"] == "ok"
    for clave in ("pr_auc", "prevalencia", "brier", "ece"):
        assert clave in resumen

    # Sin modelo activo el scoring usa baseline heuristico (Feature D)
    result = score_predicciones_retencion()
    assert result["status"] in ("baseline", "sin_vencimientos")

    activate_version(MODEL_NAME, list_versions(MODEL_NAME)[0]["version"])
    stats = score_predicciones_retencion()

    assert stats["status"] == "ok" and stats["filas"] >= 1
    with connect() as c:
        fila = c.execute(
            "SELECT prob_retencion, riesgo_cambio, model_version FROM predicciones_retencion "
            "WHERE licitacion_id = 'FUTURO'"
        ).fetchone()
    assert fila is not None
    assert fila[0] + fila[1] == pytest.approx(1.0)
    assert fila[2] == 1

    # Idempotencia del batch
    stats2 = score_predicciones_retencion()
    assert stats2["filas"] == stats["filas"]
    with connect() as c:
        total = c.execute("SELECT COUNT(*) FROM predicciones_retencion").fetchone()[0]
    assert total == stats["filas"]

    # La columna llega a la vista de renovaciones
    from services.competitive.renovaciones import proximas_renovaciones

    filas_renov = proximas_renovaciones(months_ahead=12)
    futuro = next(r for r in filas_renov if r["licitacion_id"] == "FUTURO")
    assert futuro["riesgo_cambio"] is not None
    assert futuro["retencion_model_version"] == 1


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------


def test_psi_detecta_cambio_de_distribucion():
    ref = [float(i % 100) for i in range(500)]
    assert _psi(ref, ref) == pytest.approx(0.0, abs=1e-6)
    desplazada = [v + 80 for v in ref]
    assert _psi(ref, desplazada) > 0.25


def test_comprobar_drift_sin_datos_no_explota(db):
    resultado = comprobar_drift_baja()
    assert resultado["status"] in {"sin_datos", "ok"}
