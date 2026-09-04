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
_MODEL_DIR = Path(__file__).parents[1] / "data" / "models"
_REGISTRY_PATH = _MODEL_DIR / "registry.json"


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


def _collect_negatives_from_month(
    year: int,
    month: int,
    limit: int,
    *,
    include_ti: bool,
) -> tuple[list[tuple[Any, ...]], int, int]:
    """Descarga un mes y devuelve ``(filas_negativas, descargadas, skipped_ti)``.

    Extraído de :func:`seed_negatives` para poder distribuir los negativos entre
    varios meses (evita el leakage temporal de concentrarlos en una sola
    ventana, que el split temporal del entrenamiento podría aprender como atajo).
    """
    from scraper.bulk_downloader import download_month, iter_xml_files
    from scraper.codice_parser import _text, parse_entry_unfiltered

    rows: list[tuple[Any, ...]] = []
    downloaded = 0
    skipped_ti = 0

    zip_path = download_month(year, month, force=False)
    if zip_path is None:
        log.warning("seed_negatives.no_zip", year=year, month=month)
        return rows, downloaded, skipped_ti

    _TI_PREFIXES = ("48", "72")

    # Si include_ti, necesitamos el filtro SAP para excluir licitaciones que sí
    # mencionan SAP (esas serían falsos negativos, no hard negatives).
    if include_ti:
        from scraper.filters import matches_sap

    for _filename, content in iter_xml_files(zip_path):
        if len(rows) >= limit:
            break
        try:
            from lxml import etree

            parser = etree.XMLParser(
                huge_tree=False, recover=True, resolve_entities=False, no_network=True
            )
            root = etree.fromstring(content, parser=parser)
            for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                if len(rows) >= limit:
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
                    rows.append(
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

    return rows, downloaded, skipped_ti


def seed_negatives(
    year: int | None = None,
    month: int | None = None,
    max_negatives: int = 2000,
    include_ti: bool = False,
    spread_months: int = 1,
) -> dict[str, int]:
    """Descarga bulks mensuales y persiste licitaciones como negativos.

    Estas licitaciones se guardan con raw_keywords=NULL para que el entrenamiento ML
    las use como ejemplos negativos.

    Args:
        year: Año del bulk base (defecto: mes anterior).
        month: Mes del bulk base (defecto: mes anterior).
        max_negatives: Máximo de negativos a insertar (para no inflar la BD).
        include_ti: Si True, incluye licitaciones CPV 48/72 (TI) que no
            contienen keywords SAP como "negativos difíciles" (hard negatives).
            Esto mejora la discriminación del modelo entre TI-SAP y TI-no-SAP.
        spread_months: Número de meses (hacia atrás desde el base, incluido) entre
            los que repartir ``max_negatives``. Con ``1`` (default) se comporta
            como antes (un solo mes). Con ``>1`` distribuye el cupo para que los
            negativos no se concentren en una sola ventana temporal: si no, el
            split temporal del entrenamiento podría aprender "fecha vieja →
            negativo" como atajo en lugar de la señal real.

    Returns:
        {"downloaded": N, "inserted": M, "skipped_ti": K, "already_exists": J}
    """
    from datetime import UTC, datetime

    from dateutil.relativedelta import relativedelta

    from db.database import init_db

    if year is None or month is None:
        prev = datetime.now(UTC).date() - relativedelta(months=1)
        year = year or prev.year
        month = month or prev.month

    spread_months = max(1, spread_months)
    log.info(
        "seed_negatives.start",
        year=year,
        month=month,
        max_negatives=max_negatives,
        spread_months=spread_months,
    )
    init_db()

    # Repartir el cupo entre los últimos `spread_months` meses (incluido el base).
    per_month = max(1, max_negatives // spread_months)
    base = datetime(year, month, 1, tzinfo=UTC).date()

    downloaded = 0
    skipped_ti = 0
    rows_to_insert: list[tuple[Any, ...]] = []
    for i in range(spread_months):
        if len(rows_to_insert) >= max_negatives:
            break
        m_date = base - relativedelta(months=i)
        remaining = max_negatives - len(rows_to_insert)
        month_limit = max_negatives if spread_months == 1 else min(per_month, remaining)
        month_rows, m_downloaded, m_skipped = _collect_negatives_from_month(
            m_date.year, m_date.month, month_limit, include_ti=include_ti
        )
        rows_to_insert.extend(month_rows)
        downloaded += m_downloaded
        skipped_ti += m_skipped

    inserted = 0
    already_exists = 0
    if rows_to_insert:
        from db.database import connect, get_table_columns

        now_sql = "NOW()"
        try:
            with connect() as _conn:
                existing_cols = set(get_table_columns(_conn, "licitaciones"))
        except Exception:
            with connect() as _c:
                cur = _c.execute("SELECT * FROM licitaciones LIMIT 0")
                existing_cols = {d[0] for d in (cur.description or [])}
        has_fecha_act = "fecha_actualizacion_fuente" in existing_cols
        has_tecnologia = "tecnologia" in existing_cols

        for row in rows_to_insert:
            extra_cols = ""
            extra_vals = ""
            extra_params: list[Any] = []
            if has_fecha_act:
                extra_cols += ", fecha_actualizacion_fuente"
                extra_vals += ", %s"
                extra_params.append(row[10])
            if has_tecnologia:
                extra_cols += ", tecnologia"
                extra_vals += ", NULL"
            with connect() as c:
                cur = c.execute(
                    f"""INSERT INTO licitaciones
                       (id_externo, titulo, descripcion, organo_contratacion,
                        importe, moneda, cpv, tipo_contrato, estado,
                        fecha_publicacion, fecha_extraccion, url, raw_keywords,
                        provincia, nuts_code, ccaa,
                        duracion_valor, duracion_unidad, fecha_inicio,
                        fecha_fin, prorroga_descripcion{extra_cols})
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,{now_sql},%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s{extra_vals})
                       ON CONFLICT(id_externo) DO NOTHING""",
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
        spread_months=spread_months,
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
    """Entrena el clasificador usando datos de la BD activa y lo guarda.

    Usa las MISMAS etiquetas que el reentrenamiento semanal
    (``scheduler.concept_drift._fetch_training_dataframe``): etiqueta base por
    keyword/tecnología, SOBRESCRITA por el feedback humano de ``ml_feedback``.
    Antes este camino —el que produce el asset de la Release que descargan todos
    los runners— seleccionaba solo ``titulo/descripcion/...`` sin ``es_relevante``,
    así que ``SAPClassifier.train`` caía a etiquetas 100% del filtro de keywords,
    ignorando el feedback y divergiendo del camino semanal para el mismo modelo.
    La lógica se replica inline (no se importa desde ``scheduler`` para no invertir
    capas: ``scraper`` es capa inferior).

    Pendiente (requiere infra de baseline + verificación con BD, ver backlog): el
    gate de promoción que sí tiene ``maybe_retrain_classifier``. Hoy sigue
    guardando si el entrenamiento no lanza ``error``.
    """
    import pandas as pd

    from db.database import connect, init_db
    from scraper.ml_classifier import SAPClassifier

    init_db()
    # Dos SELECT planos vía el protocolo DBAPI (execute/fetchall), no
    # ``pd.read_sql_query``: mismas etiquetas que el camino semanal pero sin
    # depender de que la conexión sea un connectable de pandas.
    with connect() as c:
        lic_cur = c.execute(
            "SELECT id_externo, titulo, descripcion, raw_keywords, cpv, "
            "importe, fecha_publicacion, tecnologia FROM licitaciones"
        )
        lic_rows = lic_cur.fetchall()
        lic_cols = [d[0] for d in lic_cur.description]
        # ``source = 'human'`` por el mismo motivo que en
        # ``scheduler/concept_drift.py::_fetch_training_dataframe``: el feedback
        # automático del etiquetado por LLM no puede realimentar al modelo.
        fb_cur = c.execute("SELECT expediente, relevante FROM ml_feedback WHERE source = 'human'")
        fb_rows = fb_cur.fetchall()
        fb_cols = [d[0] for d in fb_cur.description]

    lic = pd.DataFrame(lic_rows, columns=lic_cols)
    fb = pd.DataFrame(fb_rows, columns=fb_cols)

    if not lic.empty:
        # Etiqueta base: raw_keywords no vacío OR tecnología detectada.
        lic["es_relevante"] = (
            (lic["raw_keywords"].notna() & (lic["raw_keywords"] != ""))
            | (lic["tecnologia"].notna() & (lic["tecnologia"] != ""))
        ).astype(int)
        # Sobrescribir con feedback humano explícito (mayor prioridad).
        if not fb.empty:
            fb_map = dict(zip(fb["expediente"], fb["relevante"], strict=False))
            lic["es_relevante"] = lic.apply(
                lambda r: (
                    int(fb_map[r["id_externo"]]) if r["id_externo"] in fb_map else r["es_relevante"]
                ),
                axis=1,
            )

    # Con ``lic`` vacío el clasificador devuelve ``{"error": ...}`` y no se
    # guarda (mismo comportamiento que antes: train decide, no un early-return).
    clf = SAPClassifier()
    metrics = clf.train(lic)
    if "error" in metrics:
        return metrics

    # El artefacto de producción SOLO se sobrescribe si la versión nueva pasa
    # el gate. Antes este camino —el que genera el asset de la Release que
    # descargan la API y todos los runners— guardaba sin ninguna comprobación
    # y sin registrar versión, así que un entrenamiento con datos degradados
    # se promocionaba solo y no había versión previa a la que volver.
    from services.ml.promotion import promote_if_better

    resultado = promote_if_better(
        clf,
        metrics,
        name="sap_classifier",
        notes="train_from_db",
        models_dir=_MODEL_DIR,
        publicar_como=_MODEL_DIR / "sap_classifier.pkl",
    )
    metrics["promotion"] = resultado.as_dict()
    if not resultado.activada:
        log.warning(
            "train_from_db.no_promocionado",
            version=resultado.version,
            motivos=resultado.motivos_rechazo,
        )
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

    # `resolve_artifact` y no `is_available`: el segundo es un `Path.exists()`
    # sobre `data/models/`, que está en .gitignore y viene vacío en el runner,
    # así que este paso salía en `no_model` **por construcción** en cada pasada
    # de la pipeline diaria -- con el artefacto publicado en la Release desde
    # mayo y nadie bajándolo. Ver `shared/model_artifacts.py`.
    artefacto = SAPClassifier.resolve_artifact()
    if artefacto is None:
        log.warning("precompute_ml_proba.no_model")
        return {"updated": 0, "skipped_no_model": True}

    try:
        clf = SAPClassifier.load(artefacto)
    except Exception as exc:
        log.error("precompute_ml_proba.load_failed", error=str(exc))
        return {"updated": 0, "skipped_no_model": True}

    from db.database import connect

    where = "" if force else "WHERE ml_proba IS NULL"
    with connect() as c:
        rows = c.execute(
            f"SELECT id_externo, titulo, descripcion, cpv, importe, organo_contratacion "
            f"FROM licitaciones {where}"
        ).fetchall()

    if not rows:
        log.info("precompute_ml_proba.nothing_to_update")
        return {"updated": 0, "skipped_no_model": False}

    from config import settings

    use_organo = bool(getattr(settings, "ML_USE_ORGANO_FEATURE", False))

    updated = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        texts = [
            _augment_text(
                (str(r[1] or "") + " " + str(r[2] or "")).strip(),
                cpv=str(r[3]) if r[3] else None,
                importe=float(r[4]) if r[4] else None,
                organo=str(r[5]) if (use_organo and len(r) > 5 and r[5]) else None,
            )
            for r in batch
        ]
        try:
            probas = clf.pipeline.predict_proba(texts)[:, 1]
        except Exception as exc:
            log.error("precompute_ml_proba.predict_failed", batch_start=i, error=str(exc))
            continue

        with connect() as c:
            c.executemany(
                "UPDATE licitaciones SET ml_proba = %s WHERE id_externo = %s",
                [(float(proba), row[0]) for row, proba in zip(batch, probas, strict=False)],
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

    # Mismo motivo que en `precompute_ml_proba`: `is_available` es local.
    artefacto = TechnologyClassifier.resolve_artifact()
    if artefacto is None:
        log.warning("precompute_ml_tecnologias.no_model")
        return {"updated": 0, "scores_inserted": 0, "skipped_no_model": True}

    try:
        clf = TechnologyClassifier.load(artefacto)
    except Exception as exc:
        log.error("precompute_ml_tecnologias.load_failed", error=str(exc))
        return {"updated": 0, "scores_inserted": 0, "skipped_no_model": True}

    from db.database import connect

    now_sql = "NOW()"
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
        update_params: list[tuple[Any, ...]] = []
        delete_params: list[tuple[Any, ...]] = []
        score_params: list[tuple[Any, ...]] = []

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
        # executemany agrupa operaciones, minimizando round-trips de red al backend remoto.
        with connect() as c:
            if force and delete_params:
                c.executemany(
                    "DELETE FROM licitacion_tecnologia_score WHERE licitacion_id = %s",
                    delete_params,
                )
            c.executemany(
                "UPDATE licitaciones SET "
                "ml_tecnologias = %s, "
                "ml_proba_max = %s, "
                "ml_tech_principal = %s "
                "WHERE id_externo = %s",
                update_params,
            )
            c.executemany(
                "INSERT INTO licitacion_tecnologia_score "
                "(licitacion_id, tecnologia, probabilidad, "
                " threshold_aplicado, computed_at) "
                f"VALUES (%s, %s, %s, %s, {now_sql}) "
                "ON CONFLICT(licitacion_id, tecnologia) DO UPDATE SET "
                "probabilidad=excluded.probabilidad, "
                "threshold_aplicado=excluded.threshold_aplicado, "
                "computed_at=excluded.computed_at",
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
