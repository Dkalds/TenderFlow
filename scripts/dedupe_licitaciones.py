"""Detección de duplicados entre licitaciones (C5).

Marca pares de licitaciones cuya similitud coseno (TF-IDF de título +
descripción) supera el umbral configurado, escribiendo el ``id_externo``
del más antiguo en una columna ``duplicate_of`` de ``licitaciones``.

Uso::

    python scripts/dedupe_licitaciones.py --threshold 0.95 --window-days 90

El script es idempotente: solo añade la columna si no existe y no
sobrescribe valores ya marcados con un ``duplicate_of`` anterior si la
nueva similitud es menor.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from db.database import connect, get_table_columns
from observability.logging import get_logger

log = get_logger(__name__)


def _ensure_column() -> None:
    """Añade ``duplicate_of`` a ``licitaciones`` si aún no existe."""
    with connect() as c:
        cols = get_table_columns(c, "licitaciones")
        if "duplicate_of" not in cols:
            c.execute("ALTER TABLE licitaciones ADD COLUMN duplicate_of TEXT")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_licitaciones_duplicate_of "
                "ON licitaciones(duplicate_of) WHERE duplicate_of IS NOT NULL"
            )
            log.info("dedupe.column_added")


def find_duplicates(
    *, threshold: float = 0.95, window_days: int = 90
) -> list[tuple[str, str, float]]:
    """Encuentra pares (a, b, similitud) con similitud >= threshold.

    Solo compara licitaciones publicadas en los últimos ``window_days`` días
    para mantener el coste manejable (O(N²) en N).
    """
    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).date().isoformat()
    with connect() as c:
        df = pd.read_sql_query(
            "SELECT id_externo, fecha_publicacion, titulo, descripcion "
            "FROM licitaciones "
            "WHERE fecha_publicacion >= %s "
            "ORDER BY fecha_publicacion ASC",
            c,
            params=(cutoff,),
        )
    if len(df) < 2:
        log.info("dedupe.too_few_records", n=len(df))
        return []

    df["text"] = (df["titulo"].fillna("") + " " + df["descripcion"].fillna("")).str.strip()
    df = df[df["text"] != ""].reset_index(drop=True)
    if len(df) < 2:
        return []

    vec = TfidfVectorizer(
        max_features=5000,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.95,
        strip_accents="unicode",
        lowercase=True,
    )
    X = vec.fit_transform(df["text"])
    sim = cosine_similarity(X)

    pairs: list[tuple[str, str, float]] = []
    n = len(df)
    for i in range(n):
        for j in range(i + 1, n):
            s = sim[i, j]
            if s >= threshold:
                # Marcamos el más nuevo (j) como duplicado del más antiguo (i)
                pairs.append((df.iloc[j]["id_externo"], df.iloc[i]["id_externo"], float(s)))
    return pairs


def apply_duplicates(pairs: list[tuple[str, str, float]]) -> int:
    """Persiste las marcas de duplicados. Devuelve número de filas actualizadas."""
    if not pairs:
        return 0
    with connect() as c:
        updated = 0
        for dup_id, original_id, _sim in pairs:
            cur = c.execute(
                "UPDATE licitaciones SET duplicate_of = %s "
                "WHERE id_externo = %s AND (duplicate_of IS NULL OR duplicate_of = '')",
                (original_id, dup_id),
            )
            updated += cur.rowcount
    return updated


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--threshold", type=float, default=0.95, help="Cosine similarity mínima")
    p.add_argument("--window-days", type=int, default=90, help="Ventana de comparación")
    p.add_argument("--dry-run", action="store_true", help="Solo reportar, no persistir")
    args = p.parse_args()

    if not (0.5 <= args.threshold <= 1.0):
        print("--threshold debe estar en [0.5, 1.0]", file=sys.stderr)
        return 2

    _ensure_column()
    pairs = find_duplicates(threshold=args.threshold, window_days=args.window_days)
    print(f"Pares duplicados encontrados: {len(pairs)} (threshold={args.threshold})")
    if args.dry_run:
        for dup, orig, s in pairs[:20]:
            print(f"  {dup}  ←dup of→  {orig}  (sim={s:.3f})")
        if len(pairs) > 20:
            print(f"  ... y {len(pairs) - 20} más")
        return 0

    updated = apply_duplicates(pairs)
    print(f"Filas actualizadas: {updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
