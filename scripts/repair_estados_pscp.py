"""Repara el campo ``estado`` de las filas PSCP que guardaron texto crudo.

Hasta 2026-08-27 ``scraper/connectors/pscp.py`` tenía como fallback
``fase.strip().upper()[:20]``: cualquier fase catalana que no estuviera en su
tabla de mapeo se escribía cruda en ``licitaciones.estado``, truncada a 20
caracteres. De ahí salieron valores como ``"EXPEDIENT EN AVALUAC"`` (20 justos)
o ``"PUBLICACIÓ AGREGADA "`` (20 con el espacio final), que ``GET
/meta/filters`` ofrecía como opciones de filtro y que
:func:`shared.estados.abierta_sql` contaba como oportunidades vivas — 645.664
filas, el 93% del corpus.

El conector ya no los escribe y ``/meta/filters`` ya no los ofrece. Este script
arregla lo que quedó en la tabla. **No es una migración Alembic** a propósito:
es una corrección de datos, no de esquema, y se ejecuta cuando el operador
quiere y las veces que quiera.

Idempotente: la propuesta se calcula releyendo cada valor sucio con la misma
tabla ``_FASE_ESTADO`` del conector (por eso sus agujas están recortadas para
sobrevivir al truncado a 20 caracteres), y los valores que ya son canónicos se
descartan. Una segunda pasada tras ``--apply`` no encuentra nada que hacer.

Uso::

    python -m scripts.repair_estados_pscp             # dry-run (por defecto)
    python -m scripts.repair_estados_pscp --apply     # escribe
    python -m scripts.repair_estados_pscp --apply --incluir-sin-mapeo

Sin ``--apply`` no toca nada: imprime, mapeo a mapeo, cuántas filas cambiaría.

DÓNDE VIVE EL SQL
-----------------
``scripts/repair_estados_pscp.py`` no está en la whitelist TID251 de
``pyproject.toml`` (whitelist congelada: solo se quitan líneas, nunca se
añaden), así que no puede abrir conexión ni llevar SQL — ADR-022. Las dos
funciones que necesita viven en ``db/estados_repair.py``:

- ``contar_estados_por_fuente(fuente)`` — el reparto de filas por valor de
  ``estado``, de donde sale el plan.
- ``reescribir_estado(fuente, actual=…, nuevo=…)`` — el UPDATE, que devuelve
  las filas afectadas.

El import sigue siendo perezoso y tolerante: si alguien despliega este script
sin aquel módulo, explica qué falta y sale con código 2 en vez de reventar con
un ImportError críptico.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, Protocol

from shared.estados import ESTADOS_CANONICOS, normalizar_estado

if TYPE_CHECKING:
    from collections.abc import Iterator

FUENTE_POR_DEFECTO = "pscp"
_EXIT_DEPENDENCIA_AUSENTE = 2


class RepoEstados(Protocol):
    """Contrato mínimo que el script necesita de ``db/``.

    Escrito como Protocol y no como import directo porque el import es perezoso
    —el script tiene que poder arrancar y explicarse sin ``db/estados_repair``—
    y porque deja el contrato declarado en el sitio donde se consume.
    """

    def contar_estados_por_fuente(self, fuente: str) -> dict[str | None, int]: ...

    def reescribir_estado(self, fuente: str, *, actual: str, nuevo: str | None) -> int: ...


def _cargar_repo() -> RepoEstados | None:
    """Importa el módulo de ``db/`` que hace el trabajo, o ``None`` si falta.

    Import perezoso y tolerante: el script debe poder explicar la dependencia
    que le falta en vez de reventar con un ImportError críptico en la primera
    línea del fichero. Desde que ``db/estados_repair.py`` existe, este camino ya
    solo se recorre en un despliegue incompleto; se conserva porque un script de
    reparación de datos tiene que ser diagnosticable cuando falla.
    """
    try:
        import db.estados_repair as repo
    except ImportError as exc:
        # Solo se traga la ausencia de ESE módulo. Un ImportError de cualquier
        # otra cosa (psycopg mal instalado, un import roto dentro de db/) es un
        # problema real y esconderlo tras "falta la dependencia" mandaría al
        # operador a escribir un fichero que no arregla nada.
        if exc.name != "db.estados_repair":
            raise
        return None
    return repo


def _propuesta(valor: str | None) -> str | None:
    """Código canónico que debería tener una fila con ``estado = valor``.

    Devuelve ``None`` cuando no hay mapeo posible. El valor almacenado es la
    fase cruda en mayúsculas y truncada a 20 caracteres, así que se reusa el
    mapeo del conector en vez de mantener una segunda tabla que se
    desincronizaría a la primera fase nueva.
    """
    if valor is None:
        return None
    from scraper.connectors.pscp import fase_to_estado

    return fase_to_estado(valor)


def _plan(conteos: dict[str | None, int]) -> Iterator[tuple[str, str | None, int]]:
    """(valor_actual, valor_propuesto, filas) para cada valor que hay que tocar.

    Se saltan los NULL (no hay texto crudo que arreglar) y los valores ya
    canónicos: eso es lo que hace el script idempotente.
    """
    for valor, filas in sorted(conteos.items(), key=lambda kv: -kv[1]):
        if valor is None or normalizar_estado(valor) is not None:
            continue
        yield valor, _propuesta(valor), filas


def reparar(
    *,
    fuente: str = FUENTE_POR_DEFECTO,
    apply: bool = False,
    incluir_sin_mapeo: bool = False,
) -> int:
    """Imprime el plan y, con ``apply``, lo ejecuta. Devuelve el exit code."""
    repo = _cargar_repo()
    if repo is None:
        print(
            "FALTA DEPENDENCIA: db/estados_repair.py no existe.\n"
            "Este script no puede abrir conexión ni llevar SQL (ADR-022, ratchet "
            "TID251 congelado), así que necesita en db/ estas dos funciones:\n"
            "    contar_estados_por_fuente(fuente: str) -> dict[str | None, int]\n"
            "    reescribir_estado(fuente: str, *, actual: str, nuevo: str | None) -> int\n"
            "Ver el docstring del módulo para el SQL exacto que deben ejecutar.",
            file=sys.stderr,
        )
        return _EXIT_DEPENDENCIA_AUSENTE

    conteos = repo.contar_estados_por_fuente(fuente)
    plan = list(_plan(conteos))
    if not plan:
        print(f"[{fuente}] nada que reparar: todos los estados ya son canónicos.")
        return 0

    modo = "APPLY" if apply else "DRY-RUN"
    print(f"[{modo}] fuente={fuente} · vocabulario canónico: {sorted(ESTADOS_CANONICOS)}")
    # ASCII en la cabecera a propósito: la consola por defecto de Windows es
    # cp1252 y una flecha "→" aborta el script con UnicodeEncodeError antes de
    # imprimir una sola fila del plan.
    print(f"{'estado actual':<24} {'-> propuesto':<14} {'filas':>10}")

    tocadas = 0
    sin_mapeo = 0
    for actual, propuesto, filas in plan:
        etiqueta = propuesto if propuesto is not None else "(sin mapeo)"
        print(f"{actual!r:<24} {etiqueta:<14} {filas:>10}")
        if propuesto is None:
            sin_mapeo += filas
            # Sin mapeo NO se borra por defecto: dejar el texto crudo es feo
            # pero recuperable; ponerlo a NULL pierde la única pista de qué
            # fase era. Se reporta para que alguien añada la entrada al
            # conector, que es la reparación de verdad.
            if not incluir_sin_mapeo:
                continue
        if apply:
            tocadas += repo.reescribir_estado(fuente, actual=actual, nuevo=propuesto)
        else:
            tocadas += filas

    verbo = "reparadas" if apply else "se repararían"
    print(f"\n{verbo}: {tocadas} filas")
    if sin_mapeo and not incluir_sin_mapeo:
        print(
            f"sin mapeo: {sin_mapeo} filas conservan su valor actual. "
            "Añadí la fase a `_FASE_ESTADO` en scraper/connectors/pscp.py, o "
            "pasá --incluir-sin-mapeo para ponerlas a NULL (cuentan como abiertas)."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Repara licitaciones.estado con texto crudo de la PSCP (dry-run por defecto)"
    )
    parser.add_argument("--fuente", default=FUENTE_POR_DEFECTO, help="Fuente a reparar")
    parser.add_argument(
        "--apply", action="store_true", help="Escribe los cambios (sin esto, solo informa)"
    )
    parser.add_argument(
        "--incluir-sin-mapeo",
        action="store_true",
        help="También pone a NULL los estados sucios sin mapeo conocido",
    )
    args = parser.parse_args(argv)
    return reparar(
        fuente=args.fuente,
        apply=args.apply,
        incluir_sin_mapeo=args.incluir_sin_mapeo,
    )


if __name__ == "__main__":
    raise SystemExit(main())
