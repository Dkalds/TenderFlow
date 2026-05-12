"""Parser para los ficheros ATOM/CODICE del PLACSP.

Namespaces reales (draft) usados por la Plataforma:
  cbc          urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2
  cac          urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2
  cac-place-ext urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2
  cbc-place-ext urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2

Nota: los prefijos con guión ('cac-place-ext') no son válidos como nombres
XPath, por eso los remapeamos a 'cacext' y 'cbcext'.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from lxml import etree

from config import settings
from db.database import Adjudicacion, Licitacion
from observability.logging import get_logger
from scraper.filters import matches_technology
from shared.geo import nuts_to_ccaa

log = get_logger(__name__)

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cacext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbcext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}

# Regex para extraer campos del <summary> como fallback.
# Formato: "Id licitación: X; Órgano de Contratación: Y; Importe: Z EUR; Estado: W"
_SUMMARY_RE = re.compile(
    r"Id licitaci[oó]n:\s*(?P<id>[^;]+);"
    r"\s*[ÓO]rgano de Contrataci[oó]n:\s*(?P<organo>[^;]+);"
    r"\s*Importe:\s*(?P<importe>[\d.,]+)\s*(?P<moneda>\w+)?;"
    r"\s*Estado:\s*(?P<estado>[^;]+)",
    flags=re.IGNORECASE,
)


def _text(elem: Any, xpath: str) -> str | None:
    if elem is None:
        return None
    found = elem.xpath(xpath, namespaces=NS)
    if not found:
        return None
    val = found[0]
    if hasattr(val, "text"):
        return (val.text or "").strip() or None
    return str(val).strip() or None


def _float(elem: Any, xpath: str) -> float | None:
    raw = _text(elem, xpath)
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def parse_summary(summary: str | None) -> dict:
    """Extrae id/órgano/importe/estado del texto del summary."""
    if not summary:
        return {}
    m = _SUMMARY_RE.search(summary)
    if not m:
        return {}
    out = {
        "id_externo": m.group("id").strip(),
        "organo_contratacion": m.group("organo").strip(),
        "estado": m.group("estado").strip(),
        "moneda": (m.group("moneda") or "EUR").strip(),
    }
    try:
        out["importe"] = float(m.group("importe").replace(",", "."))
    except (ValueError, TypeError):
        pass
    return out


def _int(elem: Any, xpath: str) -> int | None:
    raw = _text(elem, xpath)
    if not raw:
        return None
    try:
        return int(float(raw))
    except (ValueError, TypeError):
        return None


def parse_adjudicaciones(entry: Any, licitacion_id: str) -> list[Adjudicacion]:
    """Extrae todas las adjudicaciones (TenderResult+WinningParty) de una entry."""
    cfs = "./cacext:ContractFolderStatus"
    results = entry.xpath(f"{cfs}/cac:TenderResult", namespaces=NS)
    out: list[Adjudicacion] = []
    for tr in results:
        result_code = _text(tr, "./cbc:ResultCode")
        result_desc = _text(tr, "./cbc:Description")
        award_date = _text(tr, "./cbc:AwardDate")
        n_ofertas = _int(tr, "./cbc:ReceivedTenderQuantity")
        oferta_min = _float(tr, "./cbc:LowerTenderAmount")
        oferta_max = _float(tr, "./cbc:HigherTenderAmount")
        sme_raw = _text(tr, "./cbc:SMEAwardedIndicator")
        es_pyme = None
        if sme_raw:
            es_pyme = 1 if sme_raw.strip().lower() == "true" else 0

        importe_adj = _float(
            tr, "./cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount"
        )
        importe_pag = _float(
            tr, "./cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:PayableAmount"
        )

        # Puede haber varias WinningParty (UTE)
        winners = tr.xpath("./cac:WinningParty", namespaces=NS)
        for wp in winners:
            nombre = _text(wp, "./cac:PartyName/cbc:Name")
            if not nombre:
                continue
            nif = _text(wp, "./cac:PartyIdentification/cbc:ID")
            nuts = _text(wp, "./cac:PhysicalLocation/cbc:CountrySubentityCode")
            provincia = _text(wp, "./cac:PhysicalLocation/cac:Address/cbc:CityName")
            out.append(
                Adjudicacion(
                    licitacion_id=licitacion_id,
                    nombre=nombre.strip(),
                    nif=nif.strip() if nif else None,
                    provincia=provincia,
                    nuts_code=nuts,
                    ccaa=nuts_to_ccaa(nuts),
                    importe_adjudicado=importe_adj,
                    importe_pagable=importe_pag,
                    fecha_adjudicacion=award_date,
                    es_pyme=es_pyme,
                    n_ofertas_recibidas=n_ofertas,
                    oferta_minima=oferta_min,
                    oferta_maxima=oferta_max,
                    result_code=result_code,
                    result_description=result_desc,
                )
            )
    return out


def _issue_date(entry: Any, cfs: str) -> str | None:
    """Extrae la primera fecha de publicación (IssueDate) de ValidNoticeInfo."""
    dates = entry.xpath(
        f"{cfs}/cacext:ValidNoticeInfo"
        "/cacext:AdditionalPublicationStatus"
        "/cacext:AdditionalPublicationDocumentReference"
        "/cbc:IssueDate/text()",
        namespaces=NS,
    )
    return min(dates) if dates else None


def parse_entry(entry: Any) -> Licitacion | None:
    """Convierte una <entry> ATOM en una Licitacion (si es de tecnología enterprise)."""
    titulo = _text(entry, "./atom:title") or ""
    summary = _text(entry, "./atom:summary")
    fecha_upd = _text(entry, "./atom:updated")

    link = entry.xpath("./atom:link/@href", namespaces=NS)
    url = link[0] if link else None

    # XPath sobre estructura CODICE
    cfs = "./cacext:ContractFolderStatus"
    id_codice = _text(entry, f"{cfs}/cbc:ContractFolderID")
    estado_codice = _text(entry, f"{cfs}/cbcext:ContractFolderStatusCode")

    organo_codice = _text(
        entry,
        f"{cfs}/cacext:LocatedContractingParty/cac:Party/cac:PartyName/cbc:Name",
    )

    project_xp = f"{cfs}/cac:ProcurementProject"
    nombre_proyecto = _text(entry, f"{project_xp}/cbc:Name")
    tipo = _text(entry, f"{project_xp}/cbc:TypeCode")
    cpv = _text(
        entry,
        f"{project_xp}/cac:RequiredCommodityClassification/cbc:ItemClassificationCode",
    )
    # TaxExclusiveAmount suele ser el importe sin IVA (licitación base)
    importe = _float(
        entry,
        f"{project_xp}/cac:BudgetAmount/cbc:TaxExclusiveAmount",
    )
    if importe is None:
        importe = _float(
            entry,
            f"{project_xp}/cac:BudgetAmount/cbc:TotalAmount",
        )
    moneda = None
    moneda_attr = entry.xpath(
        f"{project_xp}/cac:BudgetAmount/cbc:TaxExclusiveAmount/@currencyID",
        namespaces=NS,
    )
    if moneda_attr:
        moneda = moneda_attr[0]

    # Localización: provincia + código NUTS
    provincia = _text(
        entry,
        f"{project_xp}/cac:RealizedLocation/cbc:CountrySubentity",
    )
    nuts_code = _text(
        entry,
        f"{project_xp}/cac:RealizedLocation/cbc:CountrySubentityCode",
    )

    # Duración del contrato
    pp = f"{project_xp}/cac:PlannedPeriod"
    duracion_valor = _float(entry, f"{pp}/cbc:DurationMeasure")
    duracion_unidad = None
    unit_attr = entry.xpath(f"{pp}/cbc:DurationMeasure/@unitCode", namespaces=NS)
    if unit_attr:
        duracion_unidad = unit_attr[0]
    fecha_inicio = _text(entry, f"{pp}/cbc:StartDate")
    fecha_fin = _text(entry, f"{pp}/cbc:EndDate")

    prorroga = _text(
        entry,
        f"{project_xp}/cac:ContractExtension/cac:OptionValidityPeriod/cbc:Description",
    )

    # Fallback vía summary (útil cuando falta algún nodo CODICE)
    s = parse_summary(summary)

    id_externo = id_codice or s.get("id_externo")
    if not id_externo:
        # Usar el <id> atom como último recurso
        id_externo = _text(entry, "./atom:id")
    if not id_externo:
        return None

    if nombre_proyecto:
        titulo = nombre_proyecto

    is_tech, tech_kw = matches_technology(titulo, summary)
    if not is_tech:
        return None

    # Determinar tecnologías detectadas y keywords
    tecnologias = sorted(tech_kw.keys())
    all_keywords: list[str] = []
    for kw_list in tech_kw.values():
        all_keywords.extend(kw_list)
    kw = sorted(set(all_keywords))

    fecha_pub = _issue_date(entry, cfs) or fecha_upd

    return Licitacion(
        id_externo=id_externo,
        titulo=titulo or "(sin título)",
        descripcion=summary,
        organo_contratacion=organo_codice or s.get("organo_contratacion"),
        importe=importe if importe is not None else s.get("importe"),
        moneda=moneda or s.get("moneda") or "EUR",
        cpv=cpv,
        tipo_contrato=tipo,
        estado=estado_codice or s.get("estado"),
        fecha_publicacion=fecha_pub,
        fecha_actualizacion_fuente=fecha_upd,
        url=url,
        raw_keywords=",".join(kw),
        provincia=provincia,
        nuts_code=nuts_code,
        ccaa=nuts_to_ccaa(nuts_code),
        duracion_valor=duracion_valor,
        duracion_unidad=duracion_unidad,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        prorroga_descripcion=prorroga,
        tecnologia=",".join(tecnologias),
    )


def parse_entry_unfiltered(entry: Any) -> Licitacion | None:
    """Como parse_entry pero sin aplicar el filtro de tecnología.

    Útil para extraer licitaciones negativas (no-TI) para entrenamiento ML.
    Devuelve None solo si no hay id_externo válido.
    raw_keywords se deja vacío (NULL semántico) para que el clasificador las
    trate como ejemplos negativos.
    """
    titulo = _text(entry, "./atom:title") or ""
    summary = _text(entry, "./atom:summary")
    fecha_upd = _text(entry, "./atom:updated")

    link = entry.xpath("./atom:link/@href", namespaces=NS)
    url = link[0] if link else None

    cfs = "./cacext:ContractFolderStatus"
    id_codice = _text(entry, f"{cfs}/cbc:ContractFolderID")
    estado_codice = _text(entry, f"{cfs}/cbcext:ContractFolderStatusCode")
    organo_codice = _text(
        entry,
        f"{cfs}/cacext:LocatedContractingParty/cac:Party/cac:PartyName/cbc:Name",
    )

    project_xp = f"{cfs}/cac:ProcurementProject"
    nombre_proyecto = _text(entry, f"{project_xp}/cbc:Name")
    tipo = _text(entry, f"{project_xp}/cbc:TypeCode")
    cpv = _text(
        entry,
        f"{project_xp}/cac:RequiredCommodityClassification/cbc:ItemClassificationCode",
    )
    importe = _float(entry, f"{project_xp}/cac:BudgetAmount/cbc:TaxExclusiveAmount")
    if importe is None:
        importe = _float(entry, f"{project_xp}/cac:BudgetAmount/cbc:TotalAmount")
    moneda_attr = entry.xpath(
        f"{project_xp}/cac:BudgetAmount/cbc:TaxExclusiveAmount/@currencyID",
        namespaces=NS,
    )
    moneda = moneda_attr[0] if moneda_attr else None

    provincia = _text(entry, f"{project_xp}/cac:RealizedLocation/cbc:CountrySubentity")
    nuts_code = _text(
        entry, f"{project_xp}/cac:RealizedLocation/cbc:CountrySubentityCode"
    )

    pp = f"{project_xp}/cac:PlannedPeriod"
    duracion_valor = _float(entry, f"{pp}/cbc:DurationMeasure")
    unit_attr = entry.xpath(f"{pp}/cbc:DurationMeasure/@unitCode", namespaces=NS)
    duracion_unidad = unit_attr[0] if unit_attr else None
    fecha_inicio = _text(entry, f"{pp}/cbc:StartDate")
    fecha_fin = _text(entry, f"{pp}/cbc:EndDate")
    prorroga = _text(
        entry,
        f"{project_xp}/cac:ContractExtension/cac:OptionValidityPeriod/cbc:Description",
    )

    s = parse_summary(summary)
    id_externo = id_codice or s.get("id_externo") or _text(entry, "./atom:id")
    if not id_externo:
        return None

    if nombre_proyecto:
        titulo = nombre_proyecto

    fecha_pub = _issue_date(entry, cfs) or fecha_upd

    return Licitacion(
        id_externo=id_externo,
        titulo=titulo or "(sin título)",
        descripcion=summary,
        organo_contratacion=organo_codice or s.get("organo_contratacion"),
        importe=importe if importe is not None else s.get("importe"),
        moneda=moneda or s.get("moneda") or "EUR",
        cpv=cpv,
        tipo_contrato=tipo,
        estado=estado_codice or s.get("estado"),
        fecha_publicacion=fecha_pub,
        fecha_actualizacion_fuente=fecha_upd,
        url=url,
        raw_keywords=None,  # sin keywords → ejemplo negativo para ML
        provincia=provincia,
        nuts_code=nuts_code,
        ccaa=nuts_to_ccaa(nuts_code),
        duracion_valor=duracion_valor,
        duracion_unidad=duracion_unidad,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        prorroga_descripcion=prorroga,
        tecnologia=None,
    )


def parse_atom_bytes(content: bytes) -> Iterator[tuple[Licitacion, list[Adjudicacion]]]:
    """Itera (licitación, adjudicaciones) encontradas en un ATOM."""
    if len(content) > settings.MAX_XML_SIZE_BYTES:
        raise ValueError(
            f"Fichero XML demasiado grande: {len(content):,} bytes "
            f"(límite: {settings.MAX_XML_SIZE_BYTES:,}). Procesamiento abortado."
        )
    # huge_tree=False (default): mantiene límites de profundidad y tamaño de
    # lxml para prevenir ataques XML bomb. resolve_entities=False y
    # no_network=True previenen ataques XXE (XML External Entity).
    parser = etree.XMLParser(huge_tree=False, recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(content, parser=parser)
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        try:
            lic = parse_entry(entry)
            if lic:
                adj = parse_adjudicaciones(entry, lic.id_externo)
                yield lic, adj
        except Exception as e:
            log.warning("entry_parse_error", error=str(e))
