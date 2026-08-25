"""Granularidad de lote del dataset y del monitor de calibración (v86).

El lote es la unidad sobre la que se puja, pero el modelo que se **sirve**
sigue siendo el agregado por expediente: sustituirlo está condicionado a medir
antes que su ``mae_p50`` mejora. Estos tests cubren la instrumentación que hace
posible esa medida y, sobre todo, **que el camino por defecto no cambió**.

Dos bloques:

- los que tocan Postgres verifican el SQL nuevo (una fila por lote, el
  denominador correcto por fila, el expediente mixto y el emparejamiento
  predicción↔lote);
- los que no lo tocan fijan el contrato del DTO y la lógica de comparación con
  un repositorio falso, para que el gate local los vea sin BD.
"""

from __future__ import annotations

import pytest

from services.ml.calibration import (
    CalibracionBajaDTO,
    calibracion_baja_dto,
    comparar_mae_p50,
    comprobar_calibracion_baja,
)


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


# ---------------------------------------------------------------------------
# Helpers de seed
# ---------------------------------------------------------------------------


def _seed_licitacion(c, lic_id: str, importe: float) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
        " importe, tipo_contrato, fuente, fecha_publicacion, fecha_extraccion) "
        "VALUES (%s, 'Lic', 'Organo A', '72000000', 'Madrid', %s, 'Servicios', "
        " 'placsp', '2026-01-01', CURRENT_TIMESTAMP)",
        (lic_id, importe),
    )


def _seed_lote(c, lic_id: str, numero: str, importe: float, cpv: str | None = None) -> int:
    row = c.execute(
        "INSERT INTO lotes (licitacion_id, numero, cpv, importe, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP) RETURNING id",
        (lic_id, numero, cpv, importe),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _seed_adjudicacion(
    c, lic_id: str, importe_adjudicado: float, *, lote_id: int | None = None, empresa: str = "E1"
) -> None:
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, lote_id, nombre, importe_adjudicado, "
        " fecha_adjudicacion, n_ofertas_recibidas, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s, '2026-03-01', 3, CURRENT_TIMESTAMP)",
        (lic_id, lote_id, empresa, importe_adjudicado),
    )


def _seed_prediccion(
    c, lic_id: str, p10: float, p50: float, p90: float, *, lote_id: int | None = None
) -> None:
    c.execute(
        "INSERT INTO predicciones_baja (licitacion_id, lote_id, p10, p50, p90, model_version, "
        " computed_at) VALUES (%s, %s, %s, %s, %s, 1, CURRENT_TIMESTAMP)",
        (lic_id, lote_id, p10, p50, p90),
    )


def _repo():
    from db.repositories.ml_dataset import MlDatasetRepository

    return MlDatasetRepository()


# ---------------------------------------------------------------------------
# Dataset por lote
# ---------------------------------------------------------------------------


def test_multilote_da_una_fila_por_lote_con_su_propio_presupuesto(db):
    """El agregado da 1 observación; por lote, N — con el denominador del lote."""
    with db.connect() as c:
        _seed_licitacion(c, "ML1", 100_000.0)
        lote_a = _seed_lote(c, "ML1", "1", 60_000.0, cpv="72100000")
        lote_b = _seed_lote(c, "ML1", "2", 40_000.0)
        _seed_adjudicacion(c, "ML1", 45_000.0, lote_id=lote_a)  # baja 25%
        _seed_adjudicacion(c, "ML1", 36_000.0, lote_id=lote_b)  # baja 10%

    filas = _repo().pares_baja_por_lote()
    assert len(filas) == 2
    por_lote = {f["lote_id"]: f for f in filas}

    assert por_lote[lote_a]["presupuesto_efectivo"] == pytest.approx(60_000.0)
    assert por_lote[lote_a]["total_adjudicado"] == pytest.approx(45_000.0)
    assert por_lote[lote_a]["lote_numero"] == "1"
    # CPV del lote cuando existe; el del expediente cuando no.
    assert por_lote[lote_a]["cpv"] == "72100000"
    assert por_lote[lote_b]["cpv"] == "72000000"
    assert por_lote[lote_b]["presupuesto_efectivo"] == pytest.approx(40_000.0)

    # El agregado sigue viendo UNA fila contra el presupuesto de los lotes.
    agregado = _repo().pares_baja_agregada()
    assert len(agregado) == 1
    assert agregado[0]["total_adjudicado"] == pytest.approx(81_000.0)


def test_lote_unico_conserva_lote_id_nulo_y_el_importe_del_expediente(db):
    """Sin lotes parseados el expediente ES la unidad: lote_id NULL, no una fila perdida."""
    with db.connect() as c:
        _seed_licitacion(c, "UNI1", 50_000.0)
        _seed_adjudicacion(c, "UNI1", 40_000.0)

    filas = _repo().pares_baja_por_lote()
    assert len(filas) == 1
    assert filas[0]["lote_id"] is None
    assert filas[0]["lote_numero"] is None
    assert filas[0]["presupuesto_efectivo"] == pytest.approx(50_000.0)


def test_lote_adjudicado_a_dos_empresas_es_una_sola_observacion(db):
    """Dos adjudicatarios del mismo lote son una unidad de compra, no dos."""
    with db.connect() as c:
        _seed_licitacion(c, "DOS1", 100_000.0)
        lote = _seed_lote(c, "DOS1", "1", 100_000.0)
        _seed_adjudicacion(c, "DOS1", 40_000.0, lote_id=lote, empresa="A")
        _seed_adjudicacion(c, "DOS1", 35_000.0, lote_id=lote, empresa="B")

    filas = _repo().pares_baja_por_lote()
    assert len(filas) == 1
    assert filas[0]["total_adjudicado"] == pytest.approx(75_000.0)


def test_expediente_mixto_descarta_la_fila_sin_lote(db):
    """La parte sin lote no tiene denominador propio: `l.importe` ya lo cuenta el lote."""
    with db.connect() as c:
        _seed_licitacion(c, "MIX1", 100_000.0)
        lote = _seed_lote(c, "MIX1", "1", 60_000.0)
        _seed_adjudicacion(c, "MIX1", 45_000.0, lote_id=lote)
        _seed_adjudicacion(c, "MIX1", 30_000.0)  # sin lote resuelto

    filas = _repo().pares_baja_por_lote()
    assert [f["lote_id"] for f in filas] == [lote]


def test_lote_sin_presupuesto_publicado_queda_fuera(db):
    """Sin `lotes.importe` no hay denominador por lote — y no se inventa uno."""
    with db.connect() as c:
        _seed_licitacion(c, "SIN1", 100_000.0)
        lote = _seed_lote(c, "SIN1", "1", 0.0)
        _seed_adjudicacion(c, "SIN1", 45_000.0, lote_id=lote)

    assert _repo().pares_baja_por_lote() == []


def test_excluye_duplicados_confirmados_por_lote(db):
    with db.connect() as c:
        _seed_licitacion(c, "DUP1", 100_000.0)
        lote = _seed_lote(c, "DUP1", "1", 100_000.0)
        _seed_adjudicacion(c, "DUP1", 80_000.0, lote_id=lote)
        _seed_licitacion(c, "DUP2", 100_000.0)
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, confianza, "
            " status, clave_match) VALUES ('DUP1', 'DUP2', 1.0, 'confirmed', 'test')"
        )

    assert _repo().pares_baja_por_lote() == []


# ---------------------------------------------------------------------------
# Calibración por lote
# ---------------------------------------------------------------------------


def test_calibracion_por_lote_cuenta_un_par_por_lote(db):
    """Donde el agregado ve 35 pares, la vista por lote ve 70."""
    with db.connect() as c:
        for i in range(35):
            lic = f"CL{i}"
            _seed_licitacion(c, lic, 100_000.0)
            for numero in ("1", "2"):
                lote = _seed_lote(c, lic, numero, 50_000.0)
                _seed_adjudicacion(c, lic, 40_000.0, lote_id=lote)  # baja 20% por lote
            _seed_prediccion(c, lic, 0.10, 0.20, 0.30)

    agregado = comprobar_calibracion_baja()
    por_lote = comprobar_calibracion_baja("lote")

    assert agregado["n"] == 35
    assert por_lote["n"] == 70
    assert por_lote["granularidad"] == "lote"
    assert por_lote["cobertura"] == pytest.approx(1.0, abs=0.01)
    # Mientras el serving sea agregado, ningún par usa predicción propia del
    # lote: lo medido es el modelo actual visto a granularidad de lote.
    assert por_lote["n_prediccion_por_lote"] == 0


def test_la_prediccion_del_lote_gana_a_la_del_expediente(db):
    """Con predicción propia del lote, el par se evalúa contra ella."""
    with db.connect() as c:
        for i in range(35):
            lic = f"PP{i}"
            _seed_licitacion(c, lic, 100_000.0)
            lote = _seed_lote(c, lic, "1", 100_000.0)
            _seed_adjudicacion(c, lic, 80_000.0, lote_id=lote)  # baja 20%
            _seed_prediccion(c, lic, 0.15, 0.20, 0.25, lote_id=lote)

    res = comprobar_calibracion_baja("lote")
    assert res["n"] == 35
    assert res["n_prediccion_por_lote"] == 35
    assert res["mae_p50"] == pytest.approx(0.0, abs=0.001)


def test_lote_sin_prediccion_aplicable_no_entra_en_el_par(db):
    """Un lote sin predicción propia ni agregada no se empareja con nada."""
    with db.connect() as c:
        _seed_licitacion(c, "PAR1", 100_000.0)
        lote_a = _seed_lote(c, "PAR1", "1", 50_000.0)
        lote_b = _seed_lote(c, "PAR1", "2", 50_000.0)
        _seed_adjudicacion(c, "PAR1", 40_000.0, lote_id=lote_a)
        _seed_adjudicacion(c, "PAR1", 40_000.0, lote_id=lote_b)
        # Predicción sólo para el lote A (la PK por expediente aún permite una
        # única fila; el switch a varias es el commit que v86 deja preparado).
        _seed_prediccion(c, "PAR1", 0.15, 0.20, 0.25, lote_id=lote_a)

    medido = _repo().calibracion_baja_por_lote()
    assert medido["n"] == 1
    assert medido["n_prediccion_por_lote"] == 1


def test_la_granularidad_por_lote_no_altera_el_agregado(db):
    """El default sigue siendo el de siempre: mismo n, misma cobertura."""
    with db.connect() as c:
        for i in range(40):
            lic = f"AG{i}"
            _seed_licitacion(c, lic, 100_000.0)
            _seed_adjudicacion(c, lic, 80_000.0)
            _seed_prediccion(c, lic, 0.10, 0.20, 0.30)

    res = comprobar_calibracion_baja()
    assert res["status"] == "ok"
    assert res["n"] == 40
    assert res["granularidad"] == "expediente"
    assert res["cobertura"] == pytest.approx(1.0)


def test_comparar_mae_p50_no_sustituye_nada(db):
    """El gate mide y recomienda; la granularidad servida no se mueve."""
    import services.ml.calibration as cal_mod

    with db.connect() as c:
        for i in range(40):
            lic = f"CMP{i}"
            _seed_licitacion(c, lic, 100_000.0)
            _seed_adjudicacion(c, lic, 80_000.0)
            _seed_prediccion(c, lic, 0.10, 0.20, 0.30)

    res = comparar_mae_p50()
    assert res["expediente"]["granularidad"] == "expediente"
    assert res["lote"]["granularidad"] == "lote"
    assert res["recomendacion"] in {
        "sin_datos_suficientes",
        "mantener_agregado",
        "candidato_a_sustituir",
    }
    assert cal_mod.GRANULARIDAD_SERVIDA == "expediente"


def test_dto_incluir_lote_adjunta_el_desglose(db):
    with db.connect() as c:
        for i in range(35):
            lic = f"DTO{i}"
            _seed_licitacion(c, lic, 100_000.0)
            for numero in ("1", "2"):
                lote = _seed_lote(c, lic, numero, 50_000.0)
                _seed_adjudicacion(c, lic, 40_000.0, lote_id=lote)
            _seed_prediccion(c, lic, 0.10, 0.20, 0.30)

    assert calibracion_baja_dto().por_lote is None

    dto = calibracion_baja_dto(incluir_lote=True)
    assert dto.n_evaluadas == 35
    assert dto.por_lote is not None
    assert dto.por_lote.n_evaluadas == 70
    assert dto.por_lote.n_prediccion_por_lote == 0


# ---------------------------------------------------------------------------
# Contrato y comparación sin BD
# ---------------------------------------------------------------------------


def _repo_falso(agregado: dict[str, object], por_lote: dict[str, object]) -> type:
    """Clase-repositorio que devuelve medidas fijas, sin tocar Postgres."""

    class _Falso:
        def calibracion_baja(self) -> dict[str, object]:
            return agregado

        def calibracion_baja_por_lote(self) -> dict[str, object]:
            return por_lote

        def regimen_servido(self) -> str | None:
            """Sin filas de predicción no hay régimen que declarar.

            El doble tiene que implementarlo aunque estas pruebas no midan la
            atribución: ``comprobar_calibracion_baja`` es fail-open, así que un
            método que falte no explota — se convierte en ``status="error"`` y
            el test falla por un motivo que no es el suyo.

            Devolver ``None`` deja la severidad sobre el agregado, que es lo que
            estos casos fijan.
            """
            return None

    return _Falso


_BIEN = {"n": 100, "cobertura": 0.82, "mae": 0.10, "sesgo": 0.01}


def test_dto_por_defecto_no_expone_el_bloque_por_lote():
    """Aditivo de verdad: el consumidor actual ve la misma respuesta que antes."""
    dto = CalibracionBajaDTO(estado="insuficiente")
    assert dto.por_lote is None
    assert dto.granularidad == "expediente"
    campos_previos = {
        "estado",
        "cobertura",
        "cobertura_nominal",
        "mae_p50",
        "sesgo_p50",
        "n_evaluadas",
    }
    assert campos_previos <= set(dto.model_dump())


def test_comparar_mae_p50_marca_mejora_cuando_el_lote_baja_el_error(monkeypatch):
    import services.ml.calibration as cal_mod

    lote = {"n": 200, "cobertura": 0.81, "mae": 0.07, "sesgo": 0.0, "n_prediccion_por_lote": 200}
    monkeypatch.setattr(cal_mod, "MlDatasetRepository", _repo_falso(_BIEN, lote))

    res = comparar_mae_p50()
    assert res["comparable"] is True
    assert res["delta_mae_p50"] == pytest.approx(-0.03)
    assert res["mejora_lote"] is True
    assert res["recomendacion"] == "candidato_a_sustituir"


def test_comparar_mae_p50_mantiene_el_agregado_si_el_lote_no_mejora(monkeypatch):
    import services.ml.calibration as cal_mod

    lote = {"n": 200, "cobertura": 0.70, "mae": 0.14, "sesgo": 0.0, "n_prediccion_por_lote": 0}
    monkeypatch.setattr(cal_mod, "MlDatasetRepository", _repo_falso(_BIEN, lote))

    res = comparar_mae_p50()
    assert res["mejora_lote"] is False
    assert res["recomendacion"] == "mantener_agregado"


def test_comparar_mae_p50_sin_datos_no_recomienda_nada(monkeypatch):
    """Con pares insuficientes por lote no se compara contra un None."""
    import services.ml.calibration as cal_mod

    lote = {"n": 3, "cobertura": None, "mae": None, "sesgo": None, "n_prediccion_por_lote": 0}
    monkeypatch.setattr(cal_mod, "MlDatasetRepository", _repo_falso(_BIEN, lote))

    res = comparar_mae_p50()
    assert res["comparable"] is False
    assert res["delta_mae_p50"] is None
    assert res["recomendacion"] == "sin_datos_suficientes"


def test_una_degradacion_solo_por_lote_no_alerta(monkeypatch):
    """La guardia no se despierta por una granularidad que nadie está viendo."""
    import observability.alerts as alerts_mod
    import services.ml.calibration as cal_mod

    alertas: list[tuple[str, str]] = []
    monkeypatch.setattr(
        alerts_mod, "notify", lambda level, title, body="", **kw: alertas.append((level, title))
    )
    lote = {"n": 200, "cobertura": 0.10, "mae": 0.30, "sesgo": 0.2, "n_prediccion_por_lote": 0}
    monkeypatch.setattr(cal_mod, "MlDatasetRepository", _repo_falso(_BIEN, lote))

    res = comprobar_calibracion_baja("lote")
    assert res["status"] == "crit"
    assert alertas == []


def test_la_granularidad_servida_sigue_alertando(monkeypatch):
    import observability.alerts as alerts_mod
    import services.ml.calibration as cal_mod

    alertas: list[tuple[str, str]] = []
    monkeypatch.setattr(
        alerts_mod, "notify", lambda level, title, body="", **kw: alertas.append((level, title))
    )
    mal = {"n": 200, "cobertura": 0.10, "mae": 0.30, "sesgo": 0.2}
    monkeypatch.setattr(cal_mod, "MlDatasetRepository", _repo_falso(mal, mal))

    assert comprobar_calibracion_baja()["status"] == "crit"
    assert alertas, "la granularidad servida sí debe alertar"
