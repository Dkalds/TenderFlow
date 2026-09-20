"""Las bandas del Radar se declaran una sola vez: ``shared.dto.RadarBanda``.

``typing.Literal`` compara y hashea por conjunto, así que dos declaraciones de
las mismas cuatro bandas en distinto orden son el mismo tipo para las cachés de
``typing``, y el enumerado del contrato salía en el orden de quien se importase
antes: el «Codegen Drift Check» fallaba al azar. La última copia viva
(``Banda`` en ``services/watchlist_rules.py``) se sustituyó por el alias; este
test impide que vuelva otra.
"""

from __future__ import annotations

import re
from pathlib import Path

import services.watchlist_rules as watchlist_rules
from shared.dto import RadarBanda

RAIZ = Path(__file__).resolve().parents[1]
PAQUETES = ("api", "services", "shared", "db", "scheduler", "scraper", "observability")
CANONICA = RAIZ / "shared" / "dto.py"

_LITERAL = re.compile(r"Literal\[([^\]]*)\]", re.DOTALL)
_BANDAS = ("Caliente", "Atractiva", "Tibia", "Descarte")


def _declaraciones_de_bandas(texto: str) -> int:
    return sum(
        1
        for match in _LITERAL.finditer(texto)
        if all(f'"{banda}"' in match.group(1) for banda in _BANDAS)
    )


def test_ningun_modulo_de_produccion_redeclara_las_bandas() -> None:
    copias = [
        str(ruta.relative_to(RAIZ))
        for paquete in PAQUETES
        for ruta in (RAIZ / paquete).rglob("*.py")
        if ruta != CANONICA
        and "alembic" not in ruta.parts
        and _declaraciones_de_bandas(ruta.read_text(encoding="utf-8"))
    ]
    assert copias == [], f"Importa `RadarBanda` de shared.dto en vez de redeclararla: {copias}"


def test_la_canonica_existe_una_vez() -> None:
    assert _declaraciones_de_bandas(CANONICA.read_text(encoding="utf-8")) == 1


def test_watchlist_rules_usa_el_alias() -> None:
    assert not hasattr(watchlist_rules, "Banda")
    assert set(watchlist_rules.ORDEN_BANDAS) == set(RadarBanda.__args__)
    anotacion = watchlist_rules.WatchlistRule.model_fields["banda_min"].annotation
    assert anotacion == RadarBanda | None
