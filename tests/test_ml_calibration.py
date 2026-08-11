"""Tests del monitor de calibración del modelo de baja (closed-loop).

Verifica que la cobertura empírica del intervalo p10-p90 se calcula sobre los
pares predicción↔baja realizada, que respeta el umbral mínimo de evaluadas y
que degradaciones de cobertura se clasifican como warn/crit. Fail-open.
"""

from __future__ import annotations

import pytest

from services.ml.calibration import calibracion_baja_dto, comprobar_calibracion_baja


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _sembrar_par(c, lic_id, importe, baja_realizada, p10, p50, p90):
    """Inserta licitación + adjudicación (baja real) + predicción servida."""
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
        " importe, tipo_contrato, fuente, fecha_publicacion, fecha_extraccion) "
        "VALUES (%s, 'Lic', 'Organo A', '72000000', 'Madrid', %s, 'Servicios', "
        " 'placsp', '2026-01-01', CURRENT_TIMESTAMP)",
        (lic_id, importe),
    )
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
        " fecha_adjudicacion, n_ofertas_recibidas, fecha_extraccion) "
        "VALUES (%s, 'Empresa X', %s, '2026-03-01', 3, CURRENT_TIMESTAMP)",
        (lic_id, importe * (1 - baja_realizada)),
    )
    c.execute(
        "INSERT INTO predicciones_baja (licitacion_id, p10, p50, p90, model_version, "
        " computed_at) VALUES (%s, %s, %s, %s, 1, CURRENT_TIMESTAMP)",
        (lic_id, p10, p50, p90),
    )


def test_sin_suficientes_evaluadas_devuelve_sin_datos(db):
    with db.connect() as c:
        for i in range(5):
            _sembrar_par(c, f"L{i}", 100_000.0, 0.20, 0.10, 0.20, 0.30)
    res = comprobar_calibracion_baja()
    assert res["status"] == "sin_datos"
    assert res["n"] == 5


def test_intervalos_bien_calibrados_status_ok(db):
    with db.connect() as c:
        # 36 cubiertos (realizada 0.20 dentro de [0.10, 0.30]) y 4 fuera.
        for i in range(36):
            _sembrar_par(c, f"OK{i}", 100_000.0, 0.20, 0.10, 0.20, 0.30)
        for i in range(4):
            _sembrar_par(c, f"NO{i}", 100_000.0, 0.20, 0.50, 0.55, 0.60)
    res = comprobar_calibracion_baja()
    assert res["status"] == "ok"
    assert res["n"] == 40
    assert res["cobertura"] == pytest.approx(0.90, abs=0.01)


def test_intervalos_sobreconfiados_alertan(db, monkeypatch):
    alertas = []
    import observability.alerts as alerts_mod

    monkeypatch.setattr(
        alerts_mod, "notify", lambda level, title, body="", **kw: alertas.append((level, title))
    )
    with db.connect() as c:
        # Intervalo estrecho [0.19, 0.21] pero la baja real oscila mucho:
        # casi ninguno cae dentro => cobertura ~0 => crit.
        for i in range(40):
            real = 0.05 if i % 2 == 0 else 0.40
            _sembrar_par(c, f"X{i}", 100_000.0, real, 0.19, 0.20, 0.21)
    res = comprobar_calibracion_baja()
    assert res["status"] in {"warn", "crit"}
    assert res["cobertura"] < 0.65
    assert alertas, "una calibración degradada debe disparar alerta"


def test_multilote_no_infla_la_cobertura(db):
    """Un expediente multi-lote cuenta como UN par y usa la baja agregada.

    Antes del fix, el JOIN sin agregar producía una fila por lote comparando
    cada adjudicado contra el importe total del expediente (baja realizada
    ~cerca de 1.0), hundiendo la cobertura. Ahora se suman los lotes primero.
    """
    with db.connect() as c:
        for i in range(35):
            lic_id = f"ML{i}"
            # importe 100k adjudicado en dos lotes de 40k => total 80k =>
            # baja realizada agregada = 0.20, dentro de [0.10, 0.30].
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, "
                " ccaa, importe, tipo_contrato, fuente, fecha_publicacion, fecha_extraccion) "
                "VALUES (%s, 'Lic', 'Organo A', '72000000', 'Madrid', 100000.0, 'Servicios', "
                " 'placsp', '2026-01-01', CURRENT_TIMESTAMP)",
                (lic_id,),
            )
            for lote in range(2):
                c.execute(
                    "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
                    " fecha_adjudicacion, n_ofertas_recibidas, fecha_extraccion) "
                    "VALUES (%s, %s, 40000.0, '2026-03-01', 3, CURRENT_TIMESTAMP)",
                    (lic_id, f"Empresa {lote}"),
                )
            c.execute(
                "INSERT INTO predicciones_baja (licitacion_id, p10, p50, p90, model_version, "
                " computed_at) VALUES (%s, 0.10, 0.20, 0.30, 1, CURRENT_TIMESTAMP)",
                (lic_id,),
            )
    res = comprobar_calibracion_baja()
    # 35 expedientes, no 70 filas; cobertura 1.0 (todos dentro del intervalo).
    assert res["n"] == 35
    assert res["cobertura"] == pytest.approx(1.0, abs=0.01)
    assert res["status"] == "ok"


def test_excluye_duplicados_confirmados(db):
    with db.connect() as c:
        for i in range(40):
            _sembrar_par(c, f"D{i}", 100_000.0, 0.20, 0.10, 0.20, 0.30)
        # Marca 10 como duplicados confirmados: deben quedar fuera del cálculo.
        for i in range(10):
            c.execute(
                "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, "
                " confianza, status, clave_match) VALUES (%s, 'D39', 1.0, 'confirmed', 'test')",
                (f"D{i}",),
            )
    res = comprobar_calibracion_baja()
    assert res["n"] == 30


class _RepoQueRevienta:
    """Repository cuya lectura falla, para ejercitar el fail-open.

    El SQL de calibración vive en ``db.repositories.ml_dataset`` (ADR-022), así
    que el punto donde puede caerse la BD ya no es ``connect_read`` dentro de
    este módulo sino la llamada al repository.
    """

    def calibracion_baja(self) -> dict[str, object]:
        raise RuntimeError("db caída")


def test_fail_open_si_falla_la_query(db, monkeypatch):
    import services.ml.calibration as cal_mod

    monkeypatch.setattr(cal_mod, "MlDatasetRepository", _RepoQueRevienta)
    res = comprobar_calibracion_baja()
    assert res["status"] == "error"


# ---------------------------------------------------------------------------
# calibracion_baja_dto — vista pública de 3 estados (plan Pliegos+RAG, F11)
# ---------------------------------------------------------------------------


def test_dto_sin_datos_mapea_a_insuficiente(db):
    with db.connect() as c:
        for i in range(5):  # < _MIN_EVALUADAS
            _sembrar_par(c, f"L{i}", 100_000.0, 0.20, 0.10, 0.20, 0.30)
    dto = calibracion_baja_dto()
    assert dto.estado == "insuficiente"
    assert dto.n_evaluadas == 5
    assert dto.cobertura is None


def test_dto_ok_mapea_a_ok(db):
    with db.connect() as c:
        for i in range(40):
            _sembrar_par(c, f"OK{i}", 100_000.0, 0.20, 0.10, 0.20, 0.30)
    dto = calibracion_baja_dto()
    assert dto.estado == "ok"
    assert dto.n_evaluadas == 40
    assert dto.cobertura == pytest.approx(1.0)
    assert dto.cobertura_nominal == pytest.approx(0.80)
    assert dto.mae_p50 is not None
    assert dto.sesgo_p50 is not None


def test_dto_warn_y_crit_mapean_a_degradado(db):
    with db.connect() as c:
        for i in range(40):
            real = 0.05 if i % 2 == 0 else 0.40
            _sembrar_par(c, f"X{i}", 100_000.0, real, 0.19, 0.20, 0.21)
    dto = calibracion_baja_dto()
    assert dto.estado == "degradado"
    assert dto.n_evaluadas == 40


def test_dto_error_mapea_a_insuficiente(db, monkeypatch):
    """Un error interno no debe filtrar detalles al cliente -- se trata como
    'sin señal fiable todavía', igual que sin_datos."""
    import services.ml.calibration as cal_mod

    monkeypatch.setattr(cal_mod, "MlDatasetRepository", _RepoQueRevienta)
    dto = calibracion_baja_dto()
    assert dto.estado == "insuficiente"
    assert dto.cobertura is None
