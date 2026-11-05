"""``services.ml.thresholds.clasificar_psi``: los cortes del PSI, bordes incluidos."""

from __future__ import annotations

import pytest

from services.ml.thresholds import PSI_CRIT, PSI_WARN, clasificar_psi


@pytest.mark.parametrize(
    ("psi", "esperado"),
    [
        (0.0, "ok"),
        (PSI_WARN - 1e-9, "ok"),
        # El corte es inclusivo: 0.10 ya es seguimiento y 0.25 ya es drift.
        (PSI_WARN, "warn"),
        (PSI_CRIT - 1e-9, "warn"),
        (PSI_CRIT, "crit"),
        (3.0, "crit"),
    ],
)
def test_clasificar_psi(psi, esperado):
    assert clasificar_psi(psi) == esperado
