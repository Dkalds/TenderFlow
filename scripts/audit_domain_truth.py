"""Auditoría de verdad del dato — Ola 0 del plan de corrección de dominio.

Mide, contra la BD y los ZIP mensuales ya cacheados, el tamaño real de los
defectos identificados (ver docs/IMPROVEMENT_BACKLOG.md):

  (a) % de licitaciones sin ``fecha_limite`` por fuente.
  (b) Expedientes con >1 ``TenderResult`` en los ZIP cacheados — proxy de
      multi-lote no modelado.
  (c) Adjudicaciones que comparten (licitacion_id, fecha_adjudicacion,
      importe_adjudicado) con distinto NIF — proxy de UTE mal contada.
  (d) Delta de ``baja_media_pct`` calculada por-adjudicación (código actual)
      vs. agregada por-licitación (el cálculo correcto).

Cada sección es independiente: un fallo en una no bloquea las demás. Pensado
para correr antes y después del fix de Ola 1 (fecha_limite) y de las
migraciones de Ola 2/3/4 (lotes, UTE, baja unificada), para poder comparar.

Uso: python scripts/audit_domain_truth.py [--max-zips 3]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _audit_fecha_limite() -> None:
    from db.domain_truth_audit import fecha_limite_gap_by_source

    print("── (a) Cobertura de fecha_limite por fuente ──")
    rows = fecha_limite_gap_by_source()
    if not rows:
        print("  Sin licitaciones en la BD.")
        return
    for row in rows:
        print(
            f"  {row['fuente']:<20} total={row['total']:>7}  "
            f"sin_fecha_limite={row['sin_fecha_limite']:>7}  "
            f"({row['pct_sin_fecha_limite']}%)"
        )


def _audit_multi_lote(max_zips: int) -> None:
    from lxml import etree

    from config import settings
    from scraper.bulk_downloader import iter_xml_files
    from scraper.codice_parser import NS

    print(f"\n── (b) Expedientes con >1 TenderResult (proxy multi-lote, últimos {max_zips} ZIP) ──")
    downloads_dir = settings.DOWNLOADS_DIR
    if downloads_dir is None or not downloads_dir.exists():
        print(f"  Sin ZIP cacheados en {downloads_dir} — nada que auditar.")
        return

    zips = sorted(downloads_dir.glob("placsp_*.zip"), reverse=True)[:max_zips]
    if not zips:
        print(f"  Sin ZIP cacheados en {downloads_dir} — nada que auditar.")
        return

    cfs = "./cacext:ContractFolderStatus"
    total_expedientes = 0
    multi_lote = 0
    parser = etree.XMLParser(huge_tree=False, recover=True, resolve_entities=False, no_network=True)

    for zip_path in zips:
        for _name, content in iter_xml_files(zip_path):
            try:
                root = etree.fromstring(content, parser=parser)
            except etree.XMLSyntaxError:
                continue
            for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                results = entry.xpath(f"{cfs}/cac:TenderResult", namespaces=NS)
                total_expedientes += 1
                if len(results) > 1:
                    multi_lote += 1
        print(
            f"  {zip_path.name}: acumulado {total_expedientes} expedientes, {multi_lote} multi-lote"
        )

    if total_expedientes == 0:
        print("  Ningún expediente parseable en los ZIP muestreados.")
        return
    pct = round(100.0 * multi_lote / total_expedientes, 2)
    print(f"  Total: {multi_lote}/{total_expedientes} ({pct}%) expedientes con >1 TenderResult")


def _audit_ute_candidates() -> None:
    from db.domain_truth_audit import ute_candidate_stats

    print("\n── (c) Adjudicaciones candidatas a UTE mal contada ──")
    stats = ute_candidate_stats()
    print(f"  Grupos candidatos: {stats['grupos_candidatos']}")
    print(f"  Filas afectadas:   {stats['filas_afectadas']}")
    for g in stats["muestra"]:
        print(
            f"    licitacion={g['licitacion_id']}  fecha={g['fecha_adjudicacion']}  "
            f"importe={g['importe_adjudicado']}  empresas_distintas={g['empresas_distintas']}  "
            f"filas={g['filas']}"
        )


def _audit_baja_delta() -> None:
    from db.domain_truth_audit import baja_media_delta

    print("\n── (d) Delta baja_media_pct: por-adjudicación vs por-licitación ──")
    stats = baja_media_delta()
    por_adj = stats["baja_media_pct_por_adjudicacion"]
    por_lic = stats["baja_media_pct_por_licitacion"]
    print(
        f"  Por adjudicación (código actual, bajas.py):  {por_adj} (n={stats['n_por_adjudicacion']})"
    )
    print(
        f"  Por licitación (agregado, correcto):          {por_lic} (n={stats['n_por_licitacion']})"
    )
    if por_adj is not None and por_lic is not None:
        print(f"  Delta: {round(float(por_adj) - float(por_lic), 2)} puntos porcentuales")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-zips",
        type=int,
        default=3,
        help="Nº de ZIP mensuales cacheados (más recientes) a muestrear para (b).",
    )
    args = parser.parse_args()

    from db.database import init_db

    init_db()

    for section in (
        _audit_fecha_limite,
        lambda: _audit_multi_lote(args.max_zips),
        _audit_ute_candidates,
        _audit_baja_delta,
    ):
        try:
            section()
        except (
            Exception
        ) as exc:  # auditoría manual: aislar el fallo de una sección, seguir con las demás
            print(f"  ERROR en esta sección: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
