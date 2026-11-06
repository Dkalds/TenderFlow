"""``cota_hasta``: «hasta el día X incluido» sobre fechas ISO guardadas como texto."""

from __future__ import annotations

import pytest

from db.repositories.base import cota_hasta


def test_un_dia_suelto_se_compara_con_el_dia_siguiente_exclusivo() -> None:
    # Así entra '2026-04-16T19:30', que con `<= '2026-04-16'` quedaba fuera.
    assert cota_hasta("l.fecha_publicacion", "2026-04-16") == (
        "l.fecha_publicacion < %s",
        "2026-04-17",
    )


@pytest.mark.parametrize(
    ("dia", "siguiente"), [("2026-12-31", "2027-01-01"), ("2028-02-28", "2028-02-29")]
)
def test_el_dia_siguiente_cruza_meses_y_bisiestos(dia: str, siguiente: str) -> None:
    assert cota_hasta("f", dia)[1] == siguiente


def test_un_instante_completo_se_compara_tal_cual() -> None:
    assert cota_hasta("f", "2026-04-16T12:00:00+00:00") == ("f <= %s", "2026-04-16T12:00:00+00:00")
