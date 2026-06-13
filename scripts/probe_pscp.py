"""Sondeo de la API Socrata de la PSCP (paso 1 del RFC 20260611-1).

Script desechable, sin código de producción: descubre el dataset de
publicaciones de la PSCP en el portal de transparencia de la Generalitat,
muestra sus campos reales y los contrasta con los candidatos que usa
``scraper/connectors/pscp.py`` (``_FIELD_CANDIDATES``).

Uso:
    python scripts/probe_pscp.py                  # descubre candidatos de dataset
    python scripts/probe_pscp.py --dataset XXXX-XXXX   # inspecciona uno concreto

Con el dataset validado, fijá ``PSCP_DATASET_ID`` en el entorno y, si el
mapeo real difiere, ajustá ``_FIELD_CANDIDATES`` en el conector.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

DOMAIN = "analisi.transparenciacatalunya.cat"
CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"
SEARCH_TERMS = "contractació pública publicacions plataforma"
TIMEOUT = 60


def discover_datasets() -> list[dict[str, Any]]:
    resp = requests.get(
        CATALOG_URL,
        params={
            "domains": DOMAIN,
            "search_context": DOMAIN,
            "q": SEARCH_TERMS,
            "only": "datasets",
            "limit": "15",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    out = []
    for r in results:
        res = r.get("resource", {})
        out.append(
            {
                "id": res.get("id"),
                "name": res.get("name"),
                "updatedAt": res.get("updatedAt"),
                "columns": res.get("columns_field_name", []),
            }
        )
    return out


def inspect_dataset(dataset_id: str) -> None:
    url = f"https://{DOMAIN}/resource/{dataset_id}.json"
    resp = requests.get(url, params={"$limit": "3", "$order": ":id"}, timeout=TIMEOUT)
    resp.raise_for_status()
    rows = resp.json()
    print(f"\n== {dataset_id}: {len(rows)} filas de muestra ==")
    if not rows:
        return
    fields = sorted({k for row in rows for k in row})
    print("Campos reales:", ", ".join(fields))

    from scraper.connectors.pscp import _FIELD_CANDIDATES

    print("\nCobertura del mapeo del conector:")
    for concept, candidates in _FIELD_CANDIDATES.items():
        hit = next((c for c in candidates if c in fields), None)
        status = f"OK → {hit}" if hit else "SIN MATCH — ajustar _FIELD_CANDIDATES"
        print(f"  {concept:24s} {status}")

    count = requests.get(
        url.replace(".json", ".json"),
        params={"$select": "count(*) as n"},
        timeout=TIMEOUT,
    )
    if count.ok:
        print("\nVolumen total:", count.json())
    print("\nPrimera fila de muestra:")
    print(json.dumps(rows[0], indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", help="Dataset id Socrata (xxxx-xxxx) a inspeccionar")
    args = parser.parse_args()

    if args.dataset:
        inspect_dataset(args.dataset)
        return 0

    print(f"Buscando datasets de contratación en {DOMAIN}…")
    for ds in discover_datasets():
        print(f"  {ds['id']}  {ds['name']}  (updated {ds['updatedAt']})")
    print(
        "\nInspeccioná el candidato con: python scripts/probe_pscp.py --dataset <id>\n"
        "y fijá PSCP_DATASET_ID en el entorno cuando el mapeo cuadre."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
