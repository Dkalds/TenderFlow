"""``scripts/gen_status.py``: la línea «Último descenso» de cada ratchet.

Un ratchet que solo impide crecer no dice si baja. ``docs/STATUS.md`` enseña,
bajo cada uno, la fecha del último descenso y el valor de antes, leídos del
propio STATUS.md que se sobrescribe; ``--check`` tiene que seguir dando lo
mismo mientras el valor no cambie.
"""

from __future__ import annotations

from scripts.gen_status import _tendencia

_TITULO = "## Ratchet de capas — imports contra el orden de paquetes"
_HOY = "2026-11-14"


def _status(valor: int, descenso: str | None = None) -> str:
    linea = f"\n{descenso}\n" if descenso else ""
    return (
        f"# Estado\n\n{_TITULO}\n\n**{valor} imports** van de una capa a otra superior.\n"
        f"{linea}\n- `a -> b`\n\n## Motor de la suite de tests (ADR-018)\n\n**3 cosas**\n"
    )


def test_sin_status_previo_queda_sin_registrar() -> None:
    assert _tendencia("", _TITULO, 10, _HOY) == "Último descenso: sin registrar"


def test_si_el_valor_baja_el_descenso_es_de_hoy_y_dice_desde_cuanto() -> None:
    previo = _status(12, "Último descenso: 2026-10-25 (desde 21)")

    assert _tendencia(previo, _TITULO, 10, _HOY) == "Último descenso: 2026-11-14 (desde 12)"


def test_si_el_valor_no_cambia_se_conserva_la_linea() -> None:
    previo = _status(10, "Último descenso: 2026-11-05 (desde 12)")

    assert _tendencia(previo, _TITULO, 10, _HOY) == "Último descenso: 2026-11-05 (desde 12)"


def test_si_el_valor_sube_tampoco_cuenta_como_descenso() -> None:
    previo = _status(10, "Último descenso: 2026-11-05 (desde 12)")

    assert _tendencia(previo, _TITULO, 11, _HOY) == "Último descenso: 2026-11-05 (desde 12)"


def test_sin_linea_previa_y_sin_descenso_queda_sin_registrar() -> None:
    assert _tendencia(_status(10), _TITULO, 10, _HOY) == "Último descenso: sin registrar"


def test_regenerar_el_mismo_dia_tras_un_descenso_es_estable() -> None:
    """Lo que ``--check`` necesita: la segunda pasada reproduce la primera."""
    primera = _tendencia(_status(12), _TITULO, 10, _HOY)

    assert _tendencia(_status(10, primera), _TITULO, 10, "2026-12-01") == primera


def test_no_lee_el_valor_de_otra_seccion() -> None:
    """El ``**3 cosas**`` de la sección siguiente no es el valor previo del ratchet."""
    previo = f"# Estado\n\n{_TITULO}\n\nsin cifra\n\n## Otra\n\n**3 cosas**\n"

    assert _tendencia(previo, _TITULO, 2, _HOY) == "Último descenso: sin registrar"
