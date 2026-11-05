"""SQL de predecesor y similares (``db/repositories/similares.py``) contra Postgres.

``services/similares.py`` ordena y decide; sus tests doblan este módulo. Aquí
se fija qué candidatos llegan: el predecesor exige mismo órgano, mismo CPV4,
adjudicación y anterioridad; el similar solo el CPV4.
"""

from __future__ import annotations

from typing import Any

from db.repositories.similares import candidatos_a_predecesor, candidatos_a_similar, objetivo

_AHORA = "2026-10-01T00:00:00+00:00"
_ORGANO = "Ayuntamiento de Ávila"


def _licitacion(
    c: Any,
    id_externo: str,
    *,
    organo: str = _ORGANO,
    cpv: str = "72260000",
    publicada: str = "2025-01-10",
) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, descripcion, fecha_extraccion, fuente, "
        "organo_contratacion, cpv, fecha_publicacion, importe) "
        "VALUES (%s, 'Soporte SAP', 'Mantenimiento', %s, 'placsp', %s, %s, %s, 100.0)",
        (id_externo, _AHORA, organo, cpv, publicada),
    )


def _adjudicar(c: Any, id_externo: str, *, nif: str = "b-12.345.678") -> None:
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, nif, importe_adjudicado, "
        "fecha_adjudicacion, fecha_extraccion) VALUES (%s, 'ALFA SA', %s, 80.0, '2025-03-01', %s)",
        (id_externo, nif, _AHORA),
    )


def _predecesores(**cambios: Any) -> list[str]:
    args: dict[str, Any] = {
        "id_externo": "OBJ",
        "organo_id": None,
        "organo_contratacion": _ORGANO,
        "cpv4": "7226",
        "antes_de": "2026-01-01",
    }
    args.update(cambios)
    return [f["id_externo"] for f in candidatos_a_predecesor(**args)]


def test_objetivo_devuelve_el_expediente_con_su_descripcion(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "OBJ")

    fila = objetivo("OBJ")

    assert fila is not None
    assert (fila["id_externo"], fila["descripcion"]) == ("OBJ", "Mantenimiento")
    assert objetivo("NO-EXISTE") is None


def test_sin_cpv4_no_hay_candidatos() -> None:
    assert _predecesores(cpv4=None) == []
    assert candidatos_a_similar(id_externo="OBJ", cpv4=None) == []


def test_sin_organo_no_hay_predecesor() -> None:
    assert _predecesores(organo_contratacion="  ") == []


def test_el_predecesor_es_adjudicado_anterior_y_del_mismo_organo_y_cpv4(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "OBJ", publicada="2026-02-01")
        _licitacion(c, "PREVIO")
        _licitacion(c, "SIN-ADJUDICAR")
        _licitacion(c, "OTRO-ORGANO", organo="Diputación de Soria")
        _licitacion(c, "OTRO-CPV", cpv="48000000")
        _licitacion(c, "POSTERIOR", publicada="2026-03-01")
        for lic in ("OBJ", "PREVIO", "OTRO-ORGANO", "OTRO-CPV", "POSTERIOR"):
            _adjudicar(c, lic)

    assert _predecesores() == ["PREVIO"]


def test_el_organo_se_compara_plegado(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "PREVIO", organo="AYUNTAMIENTO DE AVILA")
        _adjudicar(c, "PREVIO")

    assert _predecesores(organo_contratacion="ayuntamiento de ávila ") == ["PREVIO"]


def test_el_predecesor_trae_la_clave_normalizada_del_adjudicatario(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "PREVIO")
        _adjudicar(c, "PREVIO", nif="b-12.345.678")

    (fila,) = candidatos_a_predecesor(
        id_externo="OBJ",
        organo_id=None,
        organo_contratacion=_ORGANO,
        cpv4="7226",
        antes_de=None,
    )

    assert (fila["adjudicatario"], fila["adjudicatario_clave"]) == ("ALFA SA", "B12345678")


def test_los_similares_son_de_cualquier_organo_mas_recientes_primero(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "OBJ")
        _licitacion(c, "VIEJO", organo="Diputación de Soria", publicada="2024-05-01")
        _licitacion(c, "NUEVO", publicada="2026-05-01")
        _licitacion(c, "OTRO-CPV", cpv="48000000")

    ids = [f["id_externo"] for f in candidatos_a_similar(id_externo="OBJ", cpv4="7226")]

    assert ids == ["NUEVO", "VIEJO"]


def test_los_similares_esconden_las_republicaciones_pendientes(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "ORIGINAL")
        _licitacion(c, "REPUBLICADA")
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, confianza, "
            "status, detectado_en) VALUES ('REPUBLICADA', 'ORIGINAL', 0.9, 'pending', %s)",
            (_AHORA,),
        )

    ids = [f["id_externo"] for f in candidatos_a_similar(id_externo="OBJ", cpv4="7226")]

    assert ids == ["ORIGINAL"]
