"""CU-30 — referencias de solvencia propuestas desde las adjudicaciones (art. 90.1.a LCSP).

``proponer`` es la parte pura: convierte las filas del repositorio en
referencias y descarta las que la organización ya declaró. La lectura y la
ventana de tres años se prueban contra Postgres en
``tests/test_s2_capacidad_permisos.py``.
"""

from __future__ import annotations

from services.referencias_sugeridas import proponer
from shared.dto import OrganizationReferencia


def _fila(licitacion_id: str, **campos: object) -> dict[str, object]:
    return {
        "licitacion_id": licitacion_id,
        "organo": "Diputación de Ourense",
        "fecha_adjudicacion": "2025-06-30",
        "importe_adjudicado": 125000.5,
        "tecnologia": "MICROSOFT",
        **campos,
    }


def test_convierte_la_adjudicacion_en_referencia_con_su_expediente() -> None:
    (referencia,) = proponer([_fila("EXP-1")], [])

    assert referencia == OrganizationReferencia(
        organo="Diputación de Ourense",
        importe_eur=125000.5,
        anio=2025,
        tecnologia="MICROSOFT",
        expediente_id="EXP-1",
    )


def test_descarta_lo_ya_declarado_por_expediente() -> None:
    declarada = OrganizationReferencia(organo="Otro", anio=2024, expediente_id="EXP-1")

    propuestas = proponer([_fila("EXP-1"), _fila("EXP-2")], [declarada])

    assert [r.expediente_id for r in propuestas] == ["EXP-2"]


def test_sin_importe_ni_tecnologia_las_deja_vacias() -> None:
    (referencia,) = proponer([_fila("EXP-1", importe_adjudicado=None, tecnologia=None)], [])

    assert (referencia.importe_eur, referencia.tecnologia) == (None, None)


def test_propone_como_mucho_diez() -> None:
    assert len(proponer([_fila(f"EXP-{i}") for i in range(15)], [])) == 10
