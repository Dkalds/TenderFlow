"""La reingesta corrige el ``fecha_publicacion`` que se guardó con hora.

Hasta el 2026-10-25 el parser CODICE guardaba el ``<updated>`` entero cuando el
aviso no traía ``ValidNoticeInfo``. El upsert conserva la fecha más temprana
(``_earliest_iso_date``) y comparaba el texto tal cual: el timestamp solo cedía
ante una fecha del mismo día, así que reingerir una versión posterior lo dejaba
para siempre. Sin BD: es la regla de fusión, no la escritura.
"""

from __future__ import annotations

import pytest

from db.upsert import _dia_iso, _earliest_iso_date


@pytest.mark.parametrize(
    ("guardada", "nueva", "esperada"),
    [
        # El caso del golden 24: mismo día, la reingesta deja solo la fecha.
        ("2026-05-22T10:11:12.155+02:00", "2026-05-22", "2026-05-22"),
        # El que no se corregía: la versión reingerida es de un día posterior.
        ("2026-05-22T10:11:12.155+02:00", "2026-06-03", "2026-05-22"),
        # Y si la reingesta trae una fecha anterior, gana esa.
        ("2026-05-22T10:11:12.155+02:00", "2026-05-20", "2026-05-20"),
        # Hora separada por espacio, como la escriben otros caminos.
        ("2026-05-22 10:11:12", "2026-06-03", "2026-05-22"),
        # Lo que ya era un día no cambia.
        ("2026-05-22", "2026-06-03", "2026-05-22"),
        ("2026-06-03", "2026-05-22", "2026-05-22"),
    ],
)
def test_la_fecha_mas_temprana_se_compara_y_se_guarda_como_dia(
    guardada: str, nueva: str, esperada: str
) -> None:
    assert _earliest_iso_date(guardada, nueva) == esperada


def test_un_nulo_no_borra_la_fecha() -> None:
    """Sin fecha nueva se queda la guardada, también recortada al día."""
    assert _earliest_iso_date("2026-05-22", None) == "2026-05-22"
    assert _earliest_iso_date("2026-05-22T10:11:12.155+02:00", None) == "2026-05-22"
    assert _earliest_iso_date(None, "2026-05-22") == "2026-05-22"
    assert _earliest_iso_date(None, None) is None


def test_un_formato_no_iso_no_se_recorta() -> None:
    """Lo que no es ISO lo atrapa el CHECK de la columna, no se esconde aquí."""
    assert _dia_iso("22/05/2026 10:00") == "22/05/2026 10:00"
    assert _dia_iso("2026-05-22") == "2026-05-22"
