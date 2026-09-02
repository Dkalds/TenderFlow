"""La ventana matinal de los digests se evalúa en hora peninsular."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scheduler.pipeline_runs import _es_ventana_matinal


@pytest.mark.parametrize(
    ("instante_utc", "esperado"),
    [
        # Verano (CEST = UTC+2): la pasada de las 04:00 UTC son las 06:00.
        (datetime(2026, 7, 15, 4, 0, tzinfo=UTC), True),
        (datetime(2026, 7, 15, 8, 0, tzinfo=UTC), True),
        (datetime(2026, 7, 15, 12, 0, tzinfo=UTC), False),
        (datetime(2026, 7, 15, 0, 0, tzinfo=UTC), False),
        # Invierno (CET = UTC+1): las 04:00 UTC son las 05:00, todavía no.
        (datetime(2026, 1, 15, 4, 0, tzinfo=UTC), False),
        (datetime(2026, 1, 15, 8, 0, tzinfo=UTC), True),
        (datetime(2026, 1, 15, 11, 0, tzinfo=UTC), False),
    ],
)
def test_ventana_matinal(instante_utc: datetime, esperado: bool) -> None:
    assert _es_ventana_matinal(instante_utc) is esperado
