"""SQL del análisis de bajas (``db/repositories/bajas.py``) contra Postgres.

``services.competitive.bajas`` decide qué base se compara; aquí se fija lo que
hace la consulta con ella: el presupuesto del lote manda sobre el del
expediente, los pares imposibles no entran, y los filtros de fecha, CCAA y
tamaño mínimo cortan donde dicen.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from db.repositories.bajas import fila_baja_de_referencia, filas_bajas_agregadas
from db.sql_fragments import SIN_IVA_CONOCIDO_SQL

_AHORA = "2026-10-01T00:00:00+00:00"


def _licitacion(
    c: Any,
    id_externo: str,
    *,
    importe: float = 100.0,
    organo: str = "Ayuntamiento A",
    cpv: str = "72200000",
    ccaa: str = "Madrid",
    importe_tipo: str | None = None,
) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion, fuente, importe, "
        "organo_contratacion, cpv, ccaa, importe_tipo) "
        "VALUES (%s, %s, %s, 'placsp', %s, %s, %s, %s, %s)",
        (id_externo, "Soporte TI", _AHORA, importe, organo, cpv, ccaa, importe_tipo),
    )


def _adjudicacion(
    c: Any,
    licitacion_id: str,
    importe: float,
    *,
    nombre: str = "ALFA SA",
    fecha: str = "2026-03-15",
    lote_id: int | None = None,
    ofertas: int | None = None,
) -> None:
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
        "fecha_adjudicacion, lote_id, n_ofertas_recibidas, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (licitacion_id, nombre, importe, fecha, lote_id, ofertas, _AHORA),
    )


def _agregadas(**cambios: Any) -> list[dict[str, Any]]:
    args: dict[str, Any] = {
        "group_by": "organo",
        "filtro_base": SIN_IVA_CONOCIDO_SQL,
        "min_contratos": 1,
        "cpv_prefix": None,
        "ccaa": None,
        "limit": 50,
        "fecha_desde": None,
        "fecha_hasta": None,
        "importe_min": None,
    }
    args.update(cambios)
    return filas_bajas_agregadas(**args)


def test_group_by_desconocido_se_rechaza_antes_de_consultar() -> None:
    with pytest.raises(ValueError, match="group_by inválido"):
        _agregadas(group_by="organo; DROP TABLE x")


def test_media_minimo_y_maximo_por_organo(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "L1")
        _licitacion(c, "L2")
        _adjudicacion(c, "L1", 80.0, ofertas=3)
        _adjudicacion(c, "L2", 90.0, ofertas=5)

    (fila,) = _agregadas()

    assert fila["grupo"] == "Ayuntamiento A"
    assert fila["contratos"] == 2
    assert (fila["baja_media_pct"], fila["baja_min_pct"], fila["baja_max_pct"]) == (
        15.0,
        10.0,
        20.0,
    )
    assert fila["ofertas_medias"] == 4.0
    assert fila["importe_total"] == 170.0


def test_el_presupuesto_del_lote_manda_sobre_el_del_expediente(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "L1", importe=1000.0)
        lote = c.execute(
            "INSERT INTO lotes (licitacion_id, numero, importe, fecha_extraccion) "
            "VALUES ('L1', '1', 100.0, %s) RETURNING id",
            (_AHORA,),
        ).fetchone()
        _adjudicacion(c, "L1", 80.0, lote_id=int(lote[0]))

    (fila,) = _agregadas()

    assert fila["baja_media_pct"] == 20.0


def test_un_adjudicado_por_encima_del_150_por_ciento_no_cuenta(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "L1")
        _licitacion(c, "L2")
        _adjudicacion(c, "L1", 80.0)
        _adjudicacion(c, "L2", 151.0)

    (fila,) = _agregadas()

    assert fila["contratos"] == 1


def test_el_filtro_de_base_descarta_lo_que_se_sabe_con_iva(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "L1", importe_tipo="con_iva")
        _adjudicacion(c, "L1", 80.0)

    assert _agregadas() == []


def test_fecha_hasta_incluye_las_adjudicaciones_con_hora_de_ese_dia(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "L1")
        _licitacion(c, "L2")
        _licitacion(c, "L3")
        _adjudicacion(c, "L1", 80.0, fecha="2026-02-28")
        _adjudicacion(c, "L2", 80.0, fecha="2026-03-31T10:00:00")
        _adjudicacion(c, "L3", 80.0, fecha="2026-04-01")

    (fila,) = _agregadas(fecha_desde=date(2026, 3, 1), fecha_hasta=date(2026, 3, 31))

    assert fila["contratos"] == 1


def test_ccaa_admite_varias_separadas_por_comas(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "L1", organo="Org Madrid", ccaa="Madrid")
        _licitacion(c, "L2", organo="Org Galicia", ccaa="Galicia")
        _licitacion(c, "L3", organo="Org Aragón", ccaa="Aragón")
        for lic in ("L1", "L2", "L3"):
            _adjudicacion(c, lic, 80.0)

    filas = _agregadas(ccaa="Madrid, Galicia")

    assert sorted(f["grupo"] for f in filas) == ["Org Galicia", "Org Madrid"]


def test_min_contratos_deja_fuera_los_grupos_pequenos(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "L1", organo="Grande")
        _licitacion(c, "L2", organo="Grande")
        _licitacion(c, "L3", organo="Pequeño")
        for lic in ("L1", "L2", "L3"):
            _adjudicacion(c, lic, 80.0)

    filas = _agregadas(min_contratos=2)

    assert [f["grupo"] for f in filas] == ["Grande"]


def test_por_empresa_sin_resolver_agrupa_por_nombre_sin_id(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "L1")
        _licitacion(c, "L2")
        _adjudicacion(c, "L1", 80.0, nombre="BETA SL")
        _adjudicacion(c, "L2", 90.0, nombre="BETA SL")

    (fila,) = _agregadas(group_by="empresa")

    assert (fila["grupo_id"], fila["grupo"], fila["contratos"]) == (None, "BETA SL", 2)


def test_referencia_acota_por_organo_y_prefijo_cpv(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "L1", organo="Org A", cpv="72200000")
        _licitacion(c, "L2", organo="Org A", cpv="48000000")
        _licitacion(c, "L3", organo="Org B", cpv="72200000")
        _adjudicacion(c, "L1", 70.0)
        _adjudicacion(c, "L2", 90.0)
        _adjudicacion(c, "L3", 90.0)

    fila = fila_baja_de_referencia(
        filtro_base=SIN_IVA_CONOCIDO_SQL, organo="Org A", cpv_prefix="72"
    )

    assert (fila["contratos"], fila["baja_media_pct"]) == (1, 30.0)


def test_referencia_de_un_segmento_vacio_es_una_fila_a_cero(tmp_db: Any) -> None:
    """Un agregado sin ``GROUP BY`` siempre devuelve fila: contratos 0 y bajas nulas."""
    fila = fila_baja_de_referencia(
        filtro_base=SIN_IVA_CONOCIDO_SQL, organo="Nadie", cpv_prefix=None
    )

    assert fila["contratos"] == 0
    assert fila["baja_media_pct"] is None


def test_bajas_del_scoring_no_cuentan_los_duplicados_confirmados(tmp_db: Any) -> None:
    """La señal de margen pide tres adjudicaciones por CPV-4: un duplicado no la llena."""
    from db.repositories.bajas import bajas_medias_del_scoring

    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        for id_externo, adjudicado in (("L1", 80.0), ("L2", 90.0), ("DUP", 70.0)):
            _licitacion(c, id_externo)
            _adjudicacion(c, id_externo, adjudicado)
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, confianza, "
            "status, detectado_en) VALUES ('DUP', 'L1', 1.0, 'confirmed', %s)",
            (_AHORA,),
        )

    por_cpv4, global_ = bajas_medias_del_scoring("2026-01-01")

    assert por_cpv4 == {}
    assert global_ == pytest.approx(0.15)
