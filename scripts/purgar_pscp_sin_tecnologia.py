"""Purga de PSCP: deja en la base de datos solo lo que el conector admitiría hoy.

Desde el 2026-09-09 el conector de PSCP no persiste avisos sin señal
tecnológica (D24), pero todo lo ingerido antes sigue ahí: medido contra
producción el 2026-09-26, **~685.000 filas de PSCP de las que ~3.300 llevan
`tecnologia`**. 100.000 de las demás tienen `analysis_universe` a NULL, que
cuenta como `technology_observed`, así que se cuelan en el Radar, en los avisos
y en la analítica como si fueran tecnología. Ver
`docs/rfc/2026-09-26-rfc-purga-pscp-sin-tecnologia.md`.

El marcado `pscp_censo` que proponía C4.1 no llegó a aplicarse nunca; esto lo
sustituye por un borrado, a petición del propietario.

Qué hace, fila a fila
---------------------
Reevalúa cada licitación de PSCP con **la misma puerta que el conector**
(`scraper.connectors.pscp.senal_tecnologica`: diccionario vigente + CPV para
las keywords ambiguas) y no con `tecnologia IS NULL`, porque esa columna se
escribió con el diccionario de su día: antes del 2026-09-14 no había términos
en catalán, y «desenvolupament de programari» salía sin etiqueta. Borrar por la
columna tiraría expedientes de TI reales.

- **Admitida** → se conserva: por keyword, o sin keyword pero con CPV 48/72
  (TI sin familia, como el `cpv_ti_universe` de PLACSP). Si sus etiquetas
  guardadas no son las que la puerta le pondría hoy, se cuenta como
  *desactualizada*; no se reescribe aquí,
  porque `tecnologia` solo la escribe el upsert de ingesta
  (`tests/test_dedup_guardrail.py` lo exige). La reingesta la corrige.
- **No admitida** → se borra, con sus dependientes (`ON DELETE CASCADE`) y sus
  referencias blandas (notificaciones, resúmenes pendientes, descartes).
- **No admitida pero con trabajo de usuario** (oportunidad, cartera,
  seguimiento, etiqueta…) → se conserva y se cuenta aparte.

El dato es público y se puede volver a traer: el conector reingiere desde
cualquier fecha con `python -m scraper.connectors.pscp --desde AAAA-MM-DD`, y
esa reingesta pasa por la misma puerta. Es también lo que refresca las
etiquetas desactualizadas.

Uso::

    python scripts/purgar_pscp_sin_tecnologia.py            # dry-run: mide y enseña ejemplos
    python scripts/purgar_pscp_sin_tecnologia.py --apply    # borra
    python scripts/purgar_pscp_sin_tecnologia.py --apply --lote-borrado 250

Es reanudable: si se corta, volver a lanzarlo continúa donde lo dejó (lo ya
borrado no vuelve a aparecer).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.repositories import purga_licitaciones as repo  # noqa: E402
from observability.logging import get_logger  # noqa: E402
from scraper.connectors.pscp import (  # noqa: E402
    MOTIVO_CPV_TI,
    SOURCE_ID,
    senal_tecnologica,
)

log = get_logger(__name__)

CONSERVAR = "conservar"
BORRAR = "borrar"


@dataclass(frozen=True, slots=True)
class Decision:
    """Qué hacer con una fila y por qué.

    ``tecnologia``/``raw_keywords`` son las etiquetas que la puerta le pondría
    hoy (vacías si no la admite); ``desactualizada`` dice si difieren de las
    guardadas o si a la fila le falta el universo que el conector escribe.
    """

    accion: str
    motivo: str
    tecnologia: str = ""
    raw_keywords: str = ""
    desactualizada: bool = False


def decidir(fila: dict[str, Any]) -> Decision:
    """La decisión de la purga para una fila. Pura: no toca la base de datos."""
    senal = senal_tecnologica(fila.get("titulo"), fila.get("cpv"))
    if not senal.admitida:
        return Decision(BORRAR, senal.motivo)
    tecnologia = ",".join(senal.tecnologias)
    raw_keywords = ",".join(senal.keywords)
    desactualizada = (
        tecnologia != (fila.get("tecnologia") or "")
        or raw_keywords != (fila.get("raw_keywords") or "")
        or fila.get("analysis_universe") is None
    )
    return Decision(CONSERVAR, senal.motivo, tecnologia, raw_keywords, desactualizada)


@dataclass
class Balance:
    """Lo que la purga hizo (o haría, en dry-run)."""

    leidas: int = 0
    acciones: Counter[str] = field(default_factory=Counter)
    motivos_borrado: Counter[str] = field(default_factory=Counter)
    #: Por qué se conserva: por keyword o solo por CPV 48/72 (sin etiquetas).
    motivos_conservadas: Counter[str] = field(default_factory=Counter)
    #: Conservadas cuyas etiquetas no son las de hoy: las arregla la reingesta.
    desactualizadas: int = 0
    protegidas: int = 0
    #: Filas borradas por tabla (`licitaciones` y las referencias blandas).
    borradas: Counter[str] = field(default_factory=Counter)
    ejemplos: dict[str, list[str]] = field(default_factory=dict)

    def ejemplo(self, clase: str, texto: str, maximo: int) -> None:
        lista = self.ejemplos.setdefault(clase, [])
        if len(lista) < maximo:
            lista.append(texto)


def _trozos(ids: list[str], n: int) -> list[list[str]]:
    return [ids[i : i + n] for i in range(0, len(ids), n)]


def recorrer(*, aplicar: bool, lote_lectura: int, lote_borrado: int, ejemplos: int) -> Balance:
    """Recorre PSCP entera por lotes y aplica (o mide) la decisión de cada fila."""
    balance = Balance()
    cursor = ""
    while True:
        filas = repo.lote_de_fuente(SOURCE_ID, despues_de=cursor, limite=lote_lectura)
        if not filas:
            break
        cursor = str(filas[-1]["id_externo"])
        borrables: list[str] = []
        for fila in filas:
            balance.leidas += 1
            d = decidir(fila)
            balance.acciones[d.accion] += 1
            etiqueta = f"[{fila.get('cpv')}] {str(fila.get('titulo') or '')[:110]}"
            if d.accion == BORRAR:
                borrables.append(str(fila["id_externo"]))
                balance.motivos_borrado[d.motivo] += 1
                balance.ejemplo(f"borrar · {d.motivo}", etiqueta, ejemplos)
                continue
            balance.motivos_conservadas[d.motivo] += 1
            if d.motivo == MOTIVO_CPV_TI:
                balance.ejemplo("conservar · solo por CPV 48/72", etiqueta, ejemplos)
            if d.desactualizada:
                balance.desactualizadas += 1
                balance.ejemplo(
                    "conservar · etiquetas desactualizadas",
                    f"{fila.get('tecnologia') or '—'} → {d.tecnologia} · {etiqueta}",
                    ejemplos,
                )

        if not aplicar:
            balance.protegidas += len(repo.ids_protegidos(borrables))
            continue
        for trozo in _trozos(borrables, lote_borrado):
            resumen = repo.purgar(trozo, fuente=SOURCE_ID)
            balance.protegidas += resumen.pop("protegidas", 0)
            balance.borradas.update(resumen)
        log.info(
            "purga_pscp_lote",
            hasta=cursor,
            leidas=balance.leidas,
            borradas=balance.borradas["licitaciones"],
        )
        print(f"  … {balance.leidas:,} leídas · {balance.borradas['licitaciones']:,} borradas")
    return balance


def _imprime_foto(titulo: str, foto: dict[str, int]) -> None:
    pct = 100.0 * foto["con_tecnologia"] / foto["total"] if foto["total"] else 0.0
    print(f"\n{titulo}")
    print(f"  filas de {SOURCE_ID}:           {foto['total']:>9,}")
    print(f"  con `tecnologia`:        {foto['con_tecnologia']:>9,}  ({pct:.2f} %)")


def _imprime_balance(b: Balance, *, aplicar: bool) -> None:
    print(f"\nBALANCE{'' if aplicar else ' (dry-run: lo que se haría)'}")
    print(f"  leídas:                              {b.leidas:>9,}")
    print(f"  se conservan (pasan la puerta):      {b.acciones[CONSERVAR]:>9,}")
    for motivo, n in b.motivos_conservadas.most_common():
        print(f"    · {motivo:<33} {n:>9,}")
    print(f"    · con etiquetas desactualizadas:   {b.desactualizadas:>9,}")
    print(f"  no pasan la puerta:                  {b.acciones[BORRAR]:>9,}")
    for motivo, n in b.motivos_borrado.most_common():
        print(f"    · {motivo:<33} {n:>9,}")
    print(f"    · protegidas por trabajo de usuario (no se borran): {b.protegidas:,}")
    for tabla, n in sorted(b.borradas.items()):
        print(f"  filas borradas en `{tabla}`: {n:,}")
    for clase, textos in sorted(b.ejemplos.items()):
        print(f"\n  Ejemplos · {clase}")
        for t in textos:
            print(f"    - {t}")


def _post_purga() -> None:
    """Refresca la superficie pública y avisa a las cachés. Best-effort.

    La vista materializada de canónicas seguiría sirviendo las filas borradas
    hasta el siguiente refresco programado; mejor no esperar.
    """
    try:
        from db.repositories.publico import refrescar_vista_canonicas

        n = refrescar_vista_canonicas()
        print(f"\nVista de canónicas refrescada: {n:,} filas.")
    except Exception as e:
        log.warning("purga_pscp_refresco_canonicas_fallido", error=str(e))
        print(f"\nAVISO: no se pudo refrescar la vista de canónicas ({e}); lo hará el job.")
    try:
        from shared.cache_signal import signal_cache_invalidation

        signal_cache_invalidation()
    except Exception:
        log.debug("purga_pscp_cache_signal_fallida", exc_info=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Purga de PSCP sin señal tecnológica")
    parser.add_argument("--apply", action="store_true", help="Borra (sin esto, dry-run)")
    parser.add_argument("--lote-lectura", type=int, default=5_000, help="Filas leídas por lote")
    parser.add_argument(
        "--lote-borrado",
        type=int,
        default=500,
        help="Licitaciones por transacción de borrado (cada una arrastra sus dependientes)",
    )
    parser.add_argument("--ejemplos", type=int, default=8, help="Ejemplos por clase en el informe")
    args = parser.parse_args(argv)

    antes = repo.contar_de_fuente(SOURCE_ID)
    _imprime_foto("ANTES", antes)

    balance = recorrer(
        aplicar=args.apply,
        lote_lectura=args.lote_lectura,
        lote_borrado=args.lote_borrado,
        ejemplos=args.ejemplos,
    )
    _imprime_balance(balance, aplicar=args.apply)

    if not args.apply:
        print("\nDRY-RUN: no se ha tocado nada. Ejecutá con --apply para aplicarlo.")
        return 0

    despues = repo.contar_de_fuente(SOURCE_ID)
    _imprime_foto("DESPUÉS", despues)
    _post_purga()
    log.info(
        "purga_pscp_done",
        antes=antes["total"],
        despues=despues["total"],
        desactualizadas=balance.desactualizadas,
        protegidas=balance.protegidas,
        **dict(balance.borradas),
    )
    print(
        "\nSiguientes pasos (RFC 2026-09-26): reingerir PSCP para refrescar las "
        f"{balance.desactualizadas:,} etiquetas desactualizadas "
        "(`python -m scraper.connectors.pscp --desde <fecha>`), `VACUUM (ANALYZE)` y "
        "`make audit-truth-check`, y anotar el delta en el RFC."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
