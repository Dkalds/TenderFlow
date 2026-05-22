"""Utilidades de entrenamiento y operaciones sobre la BD para el clasificador SAP.

Contiene:
  - ``_append_to_registry()`` / ``read_registry()`` — histórico de entrenamientos
  - ``seed_negatives()`` — descarga bulk y persiste negativos en la BD
  - ``train_from_db()`` — orquesta entrenamiento completo desde la BD
  - ``precompute_ml_proba()`` — pre-computa ml_proba para todas las licitaciones
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# Ruta del registro de entrenamientos (histórico de runs).
_REGISTRY_PATH = Path(__file__).parents[1] / "data" / "models" / "registry.json"


def _append_to_registry(entry: dict[str, Any], path: Path | None = None) -> Path:
    """Añade una entrada al registro de entrenamientos JSON (lista append-only).

    El registro permite:
      - Visualizar la evolución de métricas en el tiempo.
      - Detectar regresiones automáticamente (comparar último vs penúltimo).
      - Auditar qué modelo está en producción.
    """
    target = path or _REGISTRY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, Any]] = []
    if target.exists():
        try:
            raw = target.read_text(encoding="utf-8")
            if raw.strip():
                history = json.loads(raw)
            if not isinstance(history, list):
                history = []
        except json.JSONDecodeError:
            history = []
    history.append(dict(entry))
    target.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def read_registry(path: Path | None = None) -> list[dict[str, Any]]:
    """Lee el histórico de entrenamientos como lista de dicts (vacía si no existe)."""
    target = path or _REGISTRY_PATH
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def seed_negatives(
    year: int | None = None,
    month: int | None = None,
    max_negatives: int = 2000,
    include_ti: bool = False,
) -> dict[str, int]:
    """Descarga el bulk de un mes y persiste licitaciones como negativos.

    Estas licitaciones se guardan con raw_keywords=NULL para que el entrenamiento ML
    las use como ejemplos negativos.

    Args:
        year: Año del bulk a descargar (defecto: mes anterior).
        month: Mes del bulk a descargar (defecto: mes anterior).
        max_negatives: Máximo de negativos a insertar (para no inflar la BD).
        include_ti: Si True, incluye licitaciones CPV 48/72 (TI) que no
            contienen keywords SAP como "negativos difíciles" (hard negatives).
            Esto mejora la discriminación del modelo entre TI-SAP y TI-no-SAP.

    Returns:
        {"downloaded": N, "inserted": M, "skipped_ti": K, "already_exists": J}
    """
    from datetime import UTC, datetime

    from dateutil.relativedelta import relativedelta

    from db.database import init_db
    from scraper.bulk_downloader import download_month, iter_xml_files
    from scraper.codice_parser import _text, parse_entry_unfiltered

    if year is None or month is None:
        prev = datetime.now(UTC).date() - relativedelta(months=1)
        year = year or prev.year
        month = month or prev.month

    log.info("seed_negatives.start", year=year, month=month, max_negatives=max_negatives)
    init_db()

    zip_path = download_month(year, month, force=False)
    if zip_path is None:
        log.warning("seed_negatives.no_zip", year=year, month=month)
        return {"downloaded": 0, "inserted": 0, "skipped_ti": 0, "already_exists": 0}

    _TI_PREFIXES = ("48", "72")

    downloaded = 0
    skipped_ti = 0
    rows_to_insert: list[tuple[Any, ...]] = []

    # Si include_ti, necesitamos el filtro SAP para excluir licitaciones que sí
    # mencionan SAP (esas serían falsos negativos, no hard negatives).
    if include_ti:
        from scraper.filters import matches_sap

    for _filename, content in iter_xml_files(zip_path):
        if len(rows_to_insert) >= max_negatives:
            break
        try:
            from lxml import etree

            parser = etree.XMLParser(
                huge_tree=False, recover=True, resolve_entities=False, no_network=True
            )
            root = etree.fromstring(content, parser=parser)
            for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                if len(rows_to_insert) >= max_negatives:
                    break
                try:
                    cfs = "./cacext:ContractFolderStatus"
                    project_xp = f"{cfs}/cac:ProcurementProject"
                    cpv_raw = _text(
                        entry,
                        f"{project_xp}/cac:RequiredCommodityClassification"
                        f"/cbc:ItemClassificationCode",
                    )
                    is_ti = cpv_raw and any(cpv_raw.startswith(p) for p in _TI_PREFIXES)
                    if is_ti and not include_ti:
                        skipped_ti += 1
                        continue
                    if is_ti and include_ti:
                        # Hard negative: TI sin keywords SAP
                        # Fast XPath check before full parse
                        titulo_raw = _text(entry, "./atom:title") or ""
                        nombre_proy = _text(entry, f"{project_xp}/cbc:Name") or ""
                        summary_raw = _text(entry, "./atom:summary") or ""
                        has_sap, _ = matches_sap(titulo_raw, nombre_proy, summary_raw)
                        if has_sap:
                            skipped_ti += 1
                            continue

                    lic = parse_entry_unfiltered(entry)
                    if lic is None:
                        continue
                    downloaded += 1
                    rows_to_insert.append(
                        (
                            lic.id_externo,
                            lic.titulo,
                            lic.descripcion,
                            lic.organo_contratacion,
                            lic.importe,
                            lic.moneda,
                            lic.cpv,
                            lic.tipo_contrato,
                            lic.estado,
                            lic.fecha_publicacion,
                            lic.fecha_actualizacion_fuente,
                            lic.url,
                            lic.provincia,
                            lic.nuts_code,
                            lic.ccaa,
                            lic.duracion_valor,
                            lic.duracion_unidad,
                            lic.fecha_inicio,
                            lic.fecha_fin,
                            lic.prorroga_descripcion,
                        )
                    )
                except Exception:
                    log.debug("seed_negatives.entry_error")
        except Exception:
            log.debug("seed_negatives.file_error")

    inserted = 0
    already_exists = 0
    if rows_to_insert:
        import sqlite3

        from config import settings as _settings

        db_file = str(_settings.DB_PATH)
        with sqlite3.connect(db_file) as sqlite_conn:
            sqlite_conn.execute("PRAGMA journal_mode=WAL")
            sqlite_conn.execute("PRAGMA busy_timeout=5000")
            try:
                existing_cols = {
                    r[1] for r in sqlite_conn.execute("PRAGMA table_info(licitaciones)").fetchall()
                }
            except Exception:
                cur = sqlite_conn.execute("SELECT * FROM licitaciones LIMIT 0")
                existing_cols = {d[0] for d in (cur.description or [])}
            has_fecha_act = "fecha_actualizacion_fuente" in existing_cols
            has_tecnologia = "tecnologia" in existing_cols

            for row in rows_to_insert:
                extra_cols = ""
                extra_vals = ""
                extra_params: list[Any] = []
                if has_fecha_act:
                    extra_cols += ", fecha_actualizacion_fuente"
                    extra_vals += ", ?"
                    extra_params.append(row[10])
                if has_tecnologia:
                    extra_cols += ", tecnologia"
                    extra_vals += ", NULL"
                cur = sqlite_conn.execute(
                    f"""INSERT OR IGNORE INTO licitaciones
                       (id_externo, titulo, descripcion, organo_contratacion,
                        importe, moneda, cpv, tipo_contrato, estado,
                        fecha_publicacion, fecha_extraccion, url, raw_keywords,
                        provincia, nuts_code, ccaa,
                        duracion_valor, duracion_unidad, fecha_inicio,
                        fecha_fin, prorroga_descripcion{extra_cols})
                       VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'),?,NULL,?,?,?,?,?,?,?,?{extra_vals})""",
                    (
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                        row[4],
                        row[5],
                        row[6],
                        row[7],
                        row[8],
                        row[9],
                        row[11],
                        row[12],
                        row[13],
                        row[14],
                        row[15],
                        row[16],
                        row[17],
                        row[18],
                        row[19],
                        *extra_params,
                    ),
                )
                if cur.rowcount:
                    inserted += 1
                else:
                    already_exists += 1

    log.info(
        "seed_negatives.done",
        year=year,
        month=month,
        downloaded=downloaded,
        inserted=inserted,
        skipped_ti=skipped_ti,
        already_exists=already_exists,
    )
    return {
        "downloaded": downloaded,
        "inserted": inserted,
        "skipped_ti": skipped_ti,
        "already_exists": already_exists,
    }


def train_from_db() -> dict[str, Any]:
    """Entrena el clasificador usando datos de la BD activa y lo guarda."""
    import pandas as pd

    from db.database import connect, init_db
    from scraper.ml_classifier import SAPClassifier

    init_db()
    with connect() as c:
        cursor = c.execute(
            "SELECT titulo, descripcion, raw_keywords, cpv, importe, fecha_publicacion "
            "FROM licitaciones"
        )
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]

    df = pd.DataFrame(rows, columns=cols)
    clf = SAPClassifier()
    metrics = clf.train(df)
    if "error" not in metrics:
        clf.save()
    return metrics


def precompute_ml_proba(*, batch_size: int = 500, force: bool = False) -> dict[str, int]:
    """Pre-computa ml_proba para todas las licitaciones en la BD.

    Actualiza la columna ``ml_proba`` con P(SAP) del clasificador actual.
    Por defecto solo procesa filas donde ``ml_proba IS NULL``; con ``force=True``
    recalcula todas.

    Args:
        batch_size: Número de filas a procesar por batch (control de memoria).
        force: Si True, sobreescribe valores existentes.

    Returns:
        {"updated": N, "skipped_no_model": bool}
    """
    from scraper.ml_classifier import SAPClassifier
    from scraper.ml_pipeline import _augment_text

    if not SAPClassifier.is_available():
        log.warning("precompute_ml_proba.no_model")
        return {"updated": 0, "skipped_no_model": True}

    try:
        clf = SAPClassifier.load()
    except Exception as exc:
        log.error("precompute_ml_proba.load_failed", error=str(exc))
        return {"updated": 0, "skipped_no_model": True}

    from db.database import connect

    where = "" if force else "WHERE ml_proba IS NULL"
    with connect() as c:
        rows = c.execute(
            f"SELECT id_externo, titulo, descripcion, cpv, importe FROM licitaciones {where}"
        ).fetchall()

    if not rows:
        log.info("precompute_ml_proba.nothing_to_update")
        return {"updated": 0, "skipped_no_model": False}

    updated = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        texts = [
            _augment_text(
                (str(r[1] or "") + " " + str(r[2] or "")).strip(),
                cpv=str(r[3]) if r[3] else None,
                importe=float(r[4]) if r[4] else None,
            )
            for r in batch
        ]
        try:
            probas = clf.pipeline.predict_proba(texts)[:, 1]
        except Exception as exc:
            log.error("precompute_ml_proba.predict_failed", batch_start=i, error=str(exc))
            continue

        with connect() as c:
            for row, proba in zip(batch, probas, strict=False):
                c.execute(
                    "UPDATE licitaciones SET ml_proba = ? WHERE id_externo = ?",
                    (float(proba), row[0]),
                )
            c.commit()
        updated += len(batch)

    log.info("precompute_ml_proba.done", updated=updated)
    return {"updated": updated, "skipped_no_model": False}


def precompute_ml_tecnologias(*, batch_size: int = 500, force: bool = False) -> dict[str, Any]:
    """Pre-computa ml_tecnologias/ml_proba_max/ml_tech_principal en BD.

    Pobla también la tabla normalizada ``licitacion_tecnologia_score`` con un
    score por tecnología (modelo o fallback rules). Por defecto solo procesa
    filas donde ``ml_proba_max IS NULL``; con ``force=True`` recalcula todas.

    Args:
        batch_size: Número de filas por batch (control de memoria).
        force: Si True, sobreescribe valores existentes.

    Returns:
        ``{"updated": N, "scores_inserted": M, "skipped_no_model": bool}``.
    """
    from scraper.tech_classifier import TechnologyClassifier

    if not TechnologyClassifier.is_available():
        log.warning("precompute_ml_tecnologias.no_model")
        return {"updated": 0, "scores_inserted": 0, "skipped_no_model": True}

    try:
        clf = TechnologyClassifier.load()
    except Exception as exc:
        log.error("precompute_ml_tecnologias.load_failed", error=str(exc))
        return {"updated": 0, "scores_inserted": 0, "skipped_no_model": True}

    from db.database import connect

    where = "" if force else "WHERE ml_proba_max IS NULL"
    with connect() as c:
        rows = c.execute(
            f"SELECT id_externo, titulo, descripcion, cpv, importe FROM licitaciones {where}"
        ).fetchall()

    if not rows:
        log.info("precompute_ml_tecnologias.nothing_to_update")
        return {"updated": 0, "scores_inserted": 0, "skipped_no_model": False}

    updated = 0
    scores_inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        items = [
            {
                "text": (str(r[1] or "") + " " + str(r[2] or "")).strip(),
                "cpv": str(r[3]) if r[3] else None,
                "importe": float(r[4]) if r[4] else None,
            }
            for r in batch
        ]
        try:
            preds = clf.predict_batch(items)
        except Exception as exc:
            log.error(
                "precompute_ml_tecnologias.predict_failed",
                batch_start=i,
                error=str(exc),
            )
            continue

        # Construir listas de parámetros para executemany (1 petición HTTP por tabla).
        update_params: list[tuple] = []
        delete_params: list[tuple] = []
        score_params: list[tuple] = []

        for row, pred in zip(batch, preds, strict=False):
            lic_id = row[0]
            ml_tecnologias = ",".join(pred["predicted"]) if pred["predicted"] else None
            update_params.append(
                (ml_tecnologias, float(pred["max_proba"]), pred["principal"], lic_id)
            )
            if force:
                delete_params.append((lic_id,))
            for label, score in pred["scores"].items():
                if score <= 0.0:
                    continue
                thr = pred["thresholds"].get(label, 0.5)
                score_params.append((lic_id, label, float(score), float(thr)))
                scores_inserted += 1

        # Persistir batch con queries parametrizadas (seguro contra SQL injection).
        # executemany agrupa operaciones, minimizando round-trips HTTP a Turso.
        with connect() as c:
            if force and delete_params:
                c.executemany(
                    "DELETE FROM licitacion_tecnologia_score WHERE licitacion_id = ?",
                    delete_params,
                )
            c.executemany(
                "UPDATE licitaciones SET "
                "ml_tecnologias = ?, "
                "ml_proba_max = ?, "
                "ml_tech_principal = ? "
                "WHERE id_externo = ?",
                update_params,
            )
            c.executemany(
                "INSERT OR REPLACE INTO licitacion_tecnologia_score "
                "(licitacion_id, tecnologia, probabilidad, "
                " threshold_aplicado, computed_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                score_params,
            )
            c.commit()
        updated += len(batch)
        log.debug(
            "precompute_ml_tecnologias.batch_done",
            batch_start=i,
            batch_size=len(batch),
            scores=len(score_params),
        )

    log.info(
        "precompute_ml_tecnologias.done",
        updated=updated,
        scores_inserted=scores_inserted,
    )
    return {
        "updated": updated,
        "scores_inserted": scores_inserted,
        "skipped_no_model": False,
    }
