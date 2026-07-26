"""Seed hard negatives, retrain, recompute."""

import sys
import time
import zipfile
from pathlib import Path

from db.database import connect, init_db

# Step 1: Check current state
with connect() as c:
    total = c.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0]
    neg = c.execute(
        "SELECT COUNT(*) FROM licitaciones "
        "WHERE (raw_keywords IS NULL OR raw_keywords = '') "
        "AND (tecnologia IS NULL OR tecnologia = '')"
    ).fetchone()[0]
    ti_neg = c.execute(
        "SELECT COUNT(*) FROM licitaciones "
        "WHERE (raw_keywords IS NULL OR raw_keywords = '') "
        "AND (tecnologia IS NULL OR tecnologia = '') "
        "AND cpv IS NOT NULL AND (cpv LIKE '48%' OR cpv LIKE '72%')"
    ).fetchone()[0]

print(f"ANTES - Total: {total}, Negativos: {neg}, Hard negatives TI: {ti_neg}")
sys.stdout.flush()

# Step 2: Seed TI hard negatives directly (fast, lightweight parser)
from lxml import etree  # noqa: E402

from scraper.codice_parser import NS, _text  # noqa: E402
from scraper.filters import matches_sap  # noqa: E402

zip_path = Path("data/downloads/placsp_202604.zip")
max_negatives = 500
TI_PREFIXES = ("48", "72")

rows = []
skipped_sap = 0
total_ti = 0
total_entries = 0

t0 = time.time()
print("Parsing ZIP for TI hard negatives...")
sys.stdout.flush()

with zipfile.ZipFile(zip_path) as zf:
    for i, name in enumerate(zf.namelist()):
        if len(rows) >= max_negatives:
            break
        if not (name.lower().endswith(".atom") or name.lower().endswith(".xml")):
            continue
        print(f"  File {i + 1}/{len(zf.namelist())}: {name[:60]}... ", end="")
        sys.stdout.flush()
        with zf.open(name) as f:
            content = f.read()
        parser = etree.XMLParser(
            huge_tree=False, recover=True, resolve_entities=False, no_network=True
        )
        root = etree.fromstring(content, parser=parser)
        file_count = 0
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            total_entries += 1
            if len(rows) >= max_negatives:
                break
            cfs = "./cacext:ContractFolderStatus"
            project_xp = f"{cfs}/cac:ProcurementProject"
            cpv = _text(
                entry,
                f"{project_xp}/cac:RequiredCommodityClassification/cbc:ItemClassificationCode",
            )
            if not cpv or not any(cpv.startswith(p) for p in TI_PREFIXES):
                continue
            total_ti += 1

            # Quick SAP keyword check on title + summary
            titulo = _text(entry, "./atom:title") or ""
            nombre_proy = _text(entry, f"{project_xp}/cbc:Name") or ""
            summary = _text(entry, "./atom:summary") or ""
            has_sap, _ = matches_sap(titulo, nombre_proy, summary)
            if has_sap:
                skipped_sap += 1
                continue

            # Extract minimal fields for DB insertion
            id_ext = _text(entry, f"{cfs}/cbc:ContractFolderID")
            if not id_ext:
                continue
            link = entry.xpath("./atom:link/@href", namespaces=NS)
            url = link[0] if link else None

            file_count += 1
            rows.append((id_ext, titulo or nombre_proy, summary, cpv, url))

        print(f"found {file_count} hard negatives")
        sys.stdout.flush()
        del root, content

elapsed = time.time() - t0
print(f"Parsed {total_entries} entries in {elapsed:.1f}s")
print(f"TI entries: {total_ti}, SAP (skipped): {skipped_sap}, Hard negatives: {len(rows)}")
sys.stdout.flush()

# Step 3: Insert into DB using upsert_licitaciones (batched)
init_db()
from db.upsert import Licitacion as LicRow  # noqa: E402
from db.upsert import upsert_licitaciones  # noqa: E402

lic_objects = []
for id_ext, titulo, desc, cpv, url in rows:
    lic_objects.append(
        LicRow(
            id_externo=id_ext,
            titulo=titulo or "",
            descripcion=desc,
            cpv=cpv,
            url=url,
            raw_keywords=None,  # NULL = negative
        )
    )

print(f"Upserting {len(lic_objects)} licitaciones...")
sys.stdout.flush()
t1 = time.time()
nuevas, actualizadas = upsert_licitaciones(lic_objects)
print(f"Upserted in {time.time() - t1:.1f}s: {nuevas} new, {actualizadas} updated")
sys.stdout.flush()

# Step 3: Check after seed
with connect() as c:
    total2 = c.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0]
    neg2 = c.execute(
        "SELECT COUNT(*) FROM licitaciones "
        "WHERE (raw_keywords IS NULL OR raw_keywords = '') "
        "AND (tecnologia IS NULL OR tecnologia = '')"
    ).fetchone()[0]
    ti_neg2 = c.execute(
        "SELECT COUNT(*) FROM licitaciones "
        "WHERE (raw_keywords IS NULL OR raw_keywords = '') "
        "AND (tecnologia IS NULL OR tecnologia = '') "
        "AND cpv IS NOT NULL AND (cpv LIKE '48%' OR cpv LIKE '72%')"
    ).fetchone()[0]

print(f"DESPUÉS - Total: {total2}, Negativos: {neg2}, Hard negatives TI: {ti_neg2}")
print(f"Nuevos registros: {total2 - total}, Nuevos hard negatives TI: {ti_neg2 - ti_neg}")
sys.stdout.flush()

# Step 4: Retrain
print("\n=== Reentrenando modelo ===")
sys.stdout.flush()
from scraper.ml_training import train_from_db  # noqa: E402

metrics = train_from_db()
print("Métricas:")
for k, v in metrics.items():
    print(f"  {k}: {v}")
sys.stdout.flush()

# Step 5: Recompute ml_proba
print("\n=== Recomputando ml_proba ===")
sys.stdout.flush()
from scraper.ml_training import precompute_ml_proba  # noqa: E402

result = precompute_ml_proba(force=True, batch_size=1000)
print(f"Precompute result: {result}")
sys.stdout.flush()

# Step 6: Final verification
with connect() as c:
    total3 = c.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0]
    con_proba = c.execute(
        "SELECT COUNT(*) FROM licitaciones WHERE ml_proba IS NOT NULL"
    ).fetchone()[0]
    zona = c.execute(
        "SELECT COUNT(*) FROM licitaciones WHERE ml_proba BETWEEN 0.3 AND 0.7"
    ).fetchone()[0]
    zona2 = c.execute(
        "SELECT COUNT(*) FROM licitaciones WHERE ml_proba BETWEEN 0.2 AND 0.8"
    ).fetchone()[0]
    hi = c.execute("SELECT COUNT(*) FROM licitaciones WHERE ml_proba > 0.8").fetchone()[0]
    lo = c.execute("SELECT COUNT(*) FROM licitaciones WHERE ml_proba < 0.2").fetchone()[0]
    stats = c.execute(
        "SELECT MIN(ml_proba), AVG(ml_proba), MAX(ml_proba) FROM licitaciones WHERE ml_proba IS NOT NULL"
    ).fetchone()

print("\n=== RESULTADO FINAL ===")
print(f"Total: {total3}, Con ml_proba: {con_proba}")
print(f"MIN={stats[0]:.4f}, AVG={stats[1]:.4f}, MAX={stats[2]:.4f}")
print(f"Zona [0.2-0.8]: {zona2}")
print(f"Zona [0.3-0.7]: {zona}")
print(f"Alta confianza SAP (>0.8): {hi}")
print(f"Alta confianza NO-SAP (<0.2): {lo}")
