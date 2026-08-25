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


def _sembrar_par(
    c, lic_id, importe, baja_realizada, p10, p50, p90, model_version=1, computed_at=None
):
    """Inserta licitación + adjudicación (baja real) + predicción servida.

    ``model_version=None`` marca la fila como servida por el **baseline**, que
    es como ``services.ml.scoring`` las materializa sin modelo activo.
    """
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
        " computed_at) VALUES (%s, %s, %s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP))",
        (lic_id, p10, p50, p90, model_version, computed_at),
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


# ---------------------------------------------------------------------------
# Pares del baseline (insumo de la conformalización — services.ml.baja_model)
# ---------------------------------------------------------------------------


def test_pares_baseline_resueltos_ignora_las_filas_del_modelo(db):
    """Calibrar el baseline con intervalos que produjo el modelo mediría otra
    cosa: la corrección tiene que salir de lo que el baseline sirvió."""
    from db.repositories.ml_dataset import MlDatasetRepository

    with db.connect() as c:
        for i in range(3):
            _sembrar_par(c, f"B{i}", 100_000.0, 0.20, 0.12, 0.20, 0.28, model_version=None)
        for i in range(2):
            _sembrar_par(c, f"M{i}", 100_000.0, 0.20, 0.10, 0.20, 0.30, model_version=7)

    pares = MlDatasetRepository().pares_baseline_resueltos()

    assert len(pares) == 3
    assert all(p50 == pytest.approx(0.20) for p50, _ in pares)
    assert all(realizada == pytest.approx(0.20) for _, realizada in pares)


def test_pares_baseline_resueltos_devuelve_p50_no_el_intervalo_guardado(db):
    """Regresión de idempotencia: el offset se mide contra el intervalo crudo.

    Esta fila simula una noche posterior, con el ``p10``/``p90`` ya ensanchados
    por una corrección previa. Si el repositorio devolviera esos extremos, el
    score de la segunda pasada saldría ~0 y la anchura quedaría congelada en la
    de la primera. Devolviendo ``p50`` —que el offset nunca toca— el intervalo
    crudo se reconstruye igual noche tras noche.
    """
    from db.repositories.ml_dataset import MlDatasetRepository

    with db.connect() as c:
        # Crudo seria [0.12, 0.28]; lo guardado ya viene ensanchado.
        _sembrar_par(c, "B0", 100_000.0, 0.40, 0.00, 0.20, 0.55, model_version=None)

    pares = MlDatasetRepository().pares_baseline_resueltos()

    assert pares == [(pytest.approx(0.20), pytest.approx(0.40))]


# ---------------------------------------------------------------------------
# Segmentación por régimen de serving (modelo vs baseline)
# ---------------------------------------------------------------------------


def _sembrar_dos_regimenes(c, cuando_modelo="2026-02-01", cuando_baseline="2026-05-01"):
    """35 pares del modelo, todos cubiertos, y 35 del baseline, ninguno.

    La mezcla da justo 50% de cobertura: un número que no describe ni al modelo
    (perfecto) ni al baseline (nulo), que es la razón de ser del desglose.
    """
    for i in range(35):
        _sembrar_par(
            c,
            f"MOD{i}",
            100_000.0,
            0.20,
            0.10,
            0.20,
            0.30,
            model_version=3,
            computed_at=cuando_modelo,
        )
    for i in range(35):
        _sembrar_par(
            c,
            f"BAS{i}",
            100_000.0,
            0.20,
            0.30,
            0.35,
            0.40,
            model_version=None,
            computed_at=cuando_baseline,
        )


def test_calibracion_desglosa_los_dos_regimenes(db):
    with db.connect() as c:
        _sembrar_dos_regimenes(c)

    res = comprobar_calibracion_baja()

    assert res["n"] == 70
    assert res["cobertura"] == pytest.approx(0.50), "el agregado sigue siendo el agregado"
    assert res["por_regimen"]["modelo"]["n"] == 35
    assert res["por_regimen"]["modelo"]["cobertura"] == pytest.approx(1.0)
    assert res["por_regimen"]["baseline"]["n"] == 35
    assert res["por_regimen"]["baseline"]["cobertura"] == pytest.approx(0.0)


def test_severidad_se_atribuye_al_baseline_cuando_es_lo_servido(db):
    """El caso que motivó esto: el panel decía "el modelo está degradado"
    mientras lo servido era el baseline y no había modelo activo."""
    with db.connect() as c:
        # El baseline es lo más reciente => es lo que se está sirviendo.
        _sembrar_dos_regimenes(c, cuando_modelo="2026-02-01", cuando_baseline="2026-05-01")

    res = comprobar_calibracion_baja()

    assert res["regimen_servido"] == "baseline"
    assert res["severidad_sobre"] == "baseline"
    # Sobre la mezcla (50%) saldría "warn"; sobre lo que de verdad se sirve, crit.
    assert res["status"] == "crit"


def test_severidad_no_arrastra_al_modelo_recien_activado(db):
    """El fallo simétrico: una tanda vieja del baseline no debe teñir de rojo
    un modelo recién activado que está bien calibrado."""
    with db.connect() as c:
        _sembrar_dos_regimenes(c, cuando_modelo="2026-05-01", cuando_baseline="2026-02-01")

    res = comprobar_calibracion_baja()

    assert res["regimen_servido"] == "modelo"
    assert res["severidad_sobre"] == "modelo"
    assert res["status"] == "ok", "la mezcla habría alertado; el modelo servido está bien"
    assert res["cobertura"] == pytest.approx(0.50), "el agregado no se maquilla"


def test_severidad_cae_al_total_sin_pares_propios_del_regimen(db):
    """Con menos de _MIN_EVALUADAS pares propios, la cifra del régimen es ruido
    y se juzga el total: describe algo que sí se sirvió."""
    with db.connect() as c:
        for i in range(40):
            _sembrar_par(
                c,
                f"MOD{i}",
                100_000.0,
                0.20,
                0.30,
                0.35,
                0.40,
                model_version=3,
                computed_at="2026-02-01",
            )
        for i in range(5):  # baseline servido hoy, pero sin muestra propia
            _sembrar_par(
                c,
                f"BAS{i}",
                100_000.0,
                0.20,
                0.10,
                0.20,
                0.30,
                model_version=None,
                computed_at="2026-05-01",
            )

    res = comprobar_calibracion_baja()

    assert res["regimen_servido"] == "baseline"
    assert res["severidad_sobre"] == "total"
    assert res["status"] == "crit"


def test_regimen_servido_ignora_las_pasadas_viejas(db):
    """Lo que se sirve hoy es la última pasada de scoring, no la mayoría
    histórica de la tabla."""
    from db.repositories.ml_dataset import MlDatasetRepository

    with db.connect() as c:
        for i in range(20):
            _sembrar_par(
                c,
                f"V{i}",
                100_000.0,
                0.20,
                0.10,
                0.20,
                0.30,
                model_version=3,
                computed_at="2026-01-01",
            )
        _sembrar_par(
            c,
            "N0",
            100_000.0,
            0.20,
            0.10,
            0.20,
            0.30,
            model_version=None,
            computed_at="2026-06-01",
        )

    assert MlDatasetRepository().regimen_servido() == "baseline"


def test_dto_expone_el_regimen_servido_y_el_desglose(db):
    with db.connect() as c:
        _sembrar_dos_regimenes(c)

    dto = calibracion_baja_dto()

    assert dto.regimen_servido == "baseline"
    assert dto.baseline is not None
    assert dto.baseline.estado == "degradado"
    assert dto.baseline.n_evaluadas == 35
    assert dto.modelo is not None
    assert dto.modelo.estado == "ok"


def test_dto_sin_datos_no_inventa_desglose(db):
    """El camino ``sin_datos`` no desglosa: exponer un régimen vacío como si se
    hubiera medido sería peor que decir que no hay bloque."""
    with db.connect() as c:
        for i in range(5):
            _sembrar_par(c, f"L{i}", 100_000.0, 0.20, 0.10, 0.20, 0.30)

    dto = calibracion_baja_dto()

    assert dto.estado == "insuficiente"
    assert dto.modelo is None and dto.baseline is None
    assert dto.regimen_servido == "modelo"
