"""Siembra de negativos para el clasificador SAP desde los bulks mensuales.

Es ingesta, y por eso vive en ``scraper/``: descarga un bulk, parsea sus
entradas y persiste como negativos las que no mencionan SAP. El entrenamiento
que las consume está en ``services.ml.classifier_training``.

  - ``seed_negatives()`` — descarga bulk y persiste negativos en la BD
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)


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
