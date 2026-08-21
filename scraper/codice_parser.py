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
import unicodedata
from collections.abc import Iterator
from typing import Any

from lxml import etree

from config import settings
from db.database import Adjudicacion, DocumentoReferencia, Licitacion, Lote
from observability.logging import get_logger
from scraper.filters import matches_technology
from shared.dates import to_iso_date, to_iso_datetime
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


def parse_summary(summary: str | None) -> dict[str, Any]:
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
        # Referencia UBL estándar al lote (mismo shape que las *DocumentReference
        # de más abajo: un wrapper "X + Reference" con cbc:ID). Ausente en
        # expedientes de lote único -- lote_numero_raw queda None, resuelto a
        # lote_id=None (lote único implícito) en el punto de persistencia.
        lote_numero = _text(tr, "./cac:ProcurementProjectLotReference/cbc:ID")
        award_date = to_iso_date(_text(tr, "./cbc:AwardDate"))
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
                    lote_numero_raw=lote_numero,
                )
            )
    return out


# {tag CODICE, tipo lógico} — los tres siguen el mismo shape UBL DocumentReference
# (0..N ocurrencias cada uno; Additional en particular suele repetirse).
_DOC_REF_TAGS = (
    ("cac:LegalDocumentReference", "legal"),
    ("cac:TechnicalDocumentReference", "technical"),
    ("cac:AdditionalDocumentReference", "additional"),
)


def parse_document_references(entry: Any) -> list[DocumentoReferencia]:
    """Extrae los adjuntos (pliegos) referenciados en el CODICE de una entry.

    Recorre ``{Legal,Technical,Additional}DocumentReference`` bajo
    ``ContractFolderStatus``, cada uno con estructura UBL estándar:
    ``.../cac:Attachment/cac:ExternalReference/cbc:URI`` (+ opcional
    ``cbc:FileName``). Fase A2 del plan Pliegos+RAG — el fetcher (F7) resuelve
    la URI más tarde; este parser es puro y no descarga nada.

    Además de la URI se extraen dos campos que PLACSP sí publica siempre y que
    esta función ignoró hasta v88 (medido sobre el feed vivo: 390 entries,
    1.323 referencias, **100% de cobertura en ambos**):

    - ``cbc:DocumentHash`` → ``source_hash``. Es un hash del contenido, así que
      **no cambia cuando PLACSP re-emite el token** de la URI. Es la identidad
      con la que ``upsert_meta`` refresca la fila en vez de duplicarla.
    - ``cbc:ID`` → ``filename`` cuando no hay ``cbc:FileName``. En los adjuntos
      de PLACSP ``cbc:FileName`` no aparece nunca —por eso ``filename`` estaba
      a NULL en las 37.953 filas de producción— pero ``cbc:ID`` trae el nombre
      del fichero ("PCAP.pdf"). Se respeta la precedencia de ``cbc:FileName``
      porque es el campo que UBL define para esto y otras fuentes sí lo mandan.

    Una referencia sin URI (adjunto reservado/no publicado, frecuente en
    CODICE) se descarta silenciosamente — no es un error de parseo.
    """
    cfs = "./cacext:ContractFolderStatus"
    refs: list[DocumentoReferencia] = []
    for tag, tipo in _DOC_REF_TAGS:
        for node in entry.xpath(f"{cfs}/{tag}", namespaces=NS):
            uri = _text(node, "./cac:Attachment/cac:ExternalReference/cbc:URI")
            if not uri:
                continue
            filename = _text(node, "./cac:Attachment/cac:ExternalReference/cbc:FileName") or _text(
                node, "./cbc:ID"
            )
            source_hash = _text(node, "./cac:Attachment/cac:ExternalReference/cbc:DocumentHash")
            if source_hash:
                # El base64 puede venir partido en varias líneas dentro del XML;
                # normalizamos para que el mismo hash no genere dos identidades.
                source_hash = "".join(source_hash.split())
            refs.append(
                DocumentoReferencia(
                    tipo=tipo,
                    uri=uri,
                    filename=filename,
                    source_hash=source_hash or None,
                )
            )
    return refs


def _issue_date(entry: Any, cfs: str) -> str | None:
    """Extrae la primera fecha de publicación (IssueDate) de ValidNoticeInfo.

    Normaliza cada candidato a ISO antes de min() para que la comparación
    lexicográfica sea cronológica.
    """
    dates = entry.xpath(
        f"{cfs}/cacext:ValidNoticeInfo"
        "/cacext:AdditionalPublicationStatus"
        "/cacext:AdditionalPublicationDocumentReference"
        "/cbc:IssueDate/text()",
        namespaces=NS,
    )
    normalized = [d for d in (to_iso_date(raw) for raw in dates) if d]
    return min(normalized) if normalized else None


def _tender_deadline(root: Any, tendering_process_prefix: str) -> str | None:
    """Extrae el fin del plazo de presentación de ofertas.

    No confundir con ``ProcurementProject/PlannedPeriod/EndDate`` (fin de
    ejecución del contrato, ya extraído como ``fecha_fin``): este es el nodo
    que de verdad responde "¿hasta cuándo puedo presentarme?". Prioriza
    ``TenderSubmissionDeadlinePeriod`` (procedimiento abierto estándar); cae a
    ``ParticipationRequestReceptionPeriod`` para procedimientos con fase de
    solicitud de participación previa a la oferta (restringido, negociado).

    ``tendering_process_prefix`` es la ruta absoluta hasta el
    ``cac:TenderingProcess`` a leer -- a nivel de expediente
    (``{cfs}/cac:TenderingProcess``) o, si un lote publica su propio plazo
    (UBL lo permite anidando el mismo nodo dentro de
    ``cac:ProcurementProjectLot``), a nivel de lote (``./cac:TenderingProcess``
    relativo al elemento del lote). Mismo XPath, distinta raíz.
    """
    for period in ("TenderSubmissionDeadlinePeriod", "ParticipationRequestReceptionPeriod"):
        end_date = _text(root, f"{tendering_process_prefix}/cac:{period}/cbc:EndDate")
        if not end_date:
            continue
        end_time = _text(root, f"{tendering_process_prefix}/cac:{period}/cbc:EndTime")
        return to_iso_datetime(end_date, end_time)
    return None


def _tendering_process_codes(
    root: Any, tendering_process_prefix: str
) -> tuple[str | None, str | None]:
    """``(procedimiento, tramitación)`` del mismo bloque que ``_tender_deadline``.

    ``cbc:ProcedureCode`` (abierto / restringido / negociado / menor…) y
    ``cbc:UrgencyCode`` (ordinaria / urgente / emergencia) son hermanos de
    ``cac:TenderSubmissionDeadlinePeriod`` dentro de ``cac:TenderingProcess``,
    así que comparten prefijo con el plazo y aceptan la misma raíz relativa.

    Se guarda el **código crudo**, no su etiqueta: CODICE los publica como
    valores de sendas listas controladas (el atributo ``listURI`` apunta al
    ``.gc`` de la Plataforma) y traducirlos aquí obligaría a embeber una copia
    de esas listas en el repo, que envejece en silencio en cuanto la Plataforma
    publica una versión nueva — un código desconocido se vería como una
    etiqueta plausible pero equivocada. Para el modelo de baja el código ya es
    una categoría estable, que es todo lo que un GBM necesita; la etiqueta
    legible es trabajo de la capa de presentación, con la codelist delante.
    """
    return (
        _text(root, f"{tendering_process_prefix}/cbc:ProcedureCode"),
        _text(root, f"{tendering_process_prefix}/cbc:UrgencyCode"),
    )


# Un criterio de adjudicación se reconoce por su tipo cuando la fuente lo
# codifica en texto (UBL 2.1 / eForms usan `PRICE` y `COST`); CODICE de PLACSP
# lo codifica con números de una lista controlada cuyo significado no está en
# el repo, así que ahí manda la descripción.
_TIPOS_CRITERIO_PRECIO = frozenset({"price", "cost"})

# Tokens (ya sin acentos y en minúscula) que identifican un criterio económico.
# Deliberadamente cortos y pocos: "economic" cubre económico/económica/
# economicos, y el conjunto se queda en lo que no admite otra lectura. Añadir
# "importe" o "baja" subiría el recall a costa de capturar criterios que no son
# el precio ("importe de la garantía", "baja temeraria" como umbral), y un peso
# del precio inflado es peor para el modelo que un NULL honesto.
_TOKENS_CRITERIO_PRECIO = ("precio", "economic", "coste")

# Bandas en las que la suma de TODOS los pesos publicados declara su escala:
# ~100 son porcentajes, ~1 son fracciones. Fuera de ambas no se puede afirmar
# la escala (típico: el expediente publica solo algunos criterios, o los
# publica sin peso), y entonces el campo se queda NULL. Ver `parse_peso_precio`.
_PESO_TOTAL_PORCENTAJE = (95.0, 105.0)
_PESO_TOTAL_FRACCION = (0.95, 1.05)

# Criterios (CODICE los llama `AwardingCriteria`, UBL 2.1 `AwardingCriterion`)
# bajo `cac:AwardingTerms`. Se buscan por `local-name()` porque las dos grafías
# conviven en el feed según la versión del esquema con la que se publicó el
# expediente, y porque los subcriterios cuelgan de tags distintos
# (`SubordinateAwardingCriteria`/`...Criterion`) que aquí no hace falta nombrar.
_CRITERIO_ADJ_XPATH = "//*[local-name()='AwardingCriteria' or local-name()='AwardingCriterion']"
_CRITERIO_PESO_XPATH = "./*[local-name()='WeightNumeric' or local-name()='Weight']"
_CRITERIO_TIPO_XPATH = (
    "./*[local-name()='AwardingCriteriaTypeCode' or local-name()='AwardingCriterionTypeCode']"
)
_CRITERIO_TEXTO_XPATH = "./*[local-name()='Description' or local-name()='Name']//text()"

# Subcadena común a todas las grafías de un criterio, la del contenedor
# (`AwardingCriteria`/`AwardingCriterion`) y la de los anidados
# (`SubordinateAwardingCriteria`/`...Criterion`). Sirve para reconocer un
# ancestro-criterio sin enumerar las cuatro.
_CRITERIO_LOCALNAME = "AwardingCriteri"


def _sin_acentos(texto: str) -> str:
    """Minúsculas sin diacríticos, para comparar descripciones del feed."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(ch for ch in descompuesto if not unicodedata.combining(ch)).lower()


def _criterios_raiz(entry: Any, cfs: str) -> list[Any]:
    """Criterios de adjudicación de primer nivel (sin sus subcriterios).

    Los subcriterios reparten el peso *de su padre*, no el del expediente:
    sumarlos junto al padre contaría el mismo peso dos veces y sacaría el total
    fuera de la banda que declara la escala, convirtiendo un expediente
    perfectamente legible en un NULL. Se descarta todo nodo que tenga otro
    criterio por ancestro, subiendo hasta ``AwardingTerms``.

    El filtro compara **nombres locales**, no identidades de nodo: lxml crea los
    proxies de Python bajo demanda y apoyarse en que ``getparent()`` devuelva el
    mismo objeto sería depender de su caché.
    """
    nodos: list[Any] = list(
        entry.xpath(
            f"{cfs}/cac:TenderingTerms/cac:AwardingTerms{_CRITERIO_ADJ_XPATH}", namespaces=NS
        )
    )
    raiz: list[Any] = []
    for nodo in nodos:
        padre = nodo.getparent()
        anidado = False
        while padre is not None:
            local = etree.QName(padre).localname
            if local == "AwardingTerms":
                break
            if _CRITERIO_LOCALNAME in local:
                anidado = True
                break
            padre = padre.getparent()
        if not anidado:
            raiz.append(nodo)
    return raiz


def _es_criterio_precio(nodo: Any) -> bool:
    tipo = _text(nodo, _CRITERIO_TIPO_XPATH)
    if tipo and tipo.strip().lower() in _TIPOS_CRITERIO_PRECIO:
        return True
    textos = nodo.xpath(_CRITERIO_TEXTO_XPATH, namespaces=NS)
    plano = _sin_acentos(" ".join(str(t) for t in textos))
    return any(token in plano for token in _TOKENS_CRITERIO_PRECIO)


def parse_peso_precio(entry: Any) -> float | None:
    """Peso del precio en los criterios de adjudicación, en % sobre 100.

    El dato que mueve la baja no es "hay criterios de precio" sino *cuánto*
    pesa el precio frente a los criterios de juicio de valor: un 100% de precio
    y un 40% describen dos mercados distintos. CODICE publica cada criterio con
    su ``WeightNumeric``, pero **no publica la escala**: unos expedientes usan
    porcentajes (60, 40) y otros fracciones (0.6, 0.4).

    La escala se deduce de la suma de todos los pesos publicados: ~100 →
    porcentajes, ~1 → fracciones (por 100). Si la suma cae fuera de ambas bandas
    la escala es indeterminable — típicamente porque el expediente publica solo
    parte de los criterios, o los publica sin peso — y se devuelve ``None``.
    Devolver el número igualmente daría un porcentaje inventado sobre un
    denominador desconocido, y el modelo no tiene forma de distinguirlo de uno
    medido.

    Un expediente cuyos criterios suman bien y no incluyen ninguno económico
    devuelve ``0.0``, que es información real (adjudicación solo por calidad),
    no ausencia de dato.
    """
    cfs = "./cacext:ContractFolderStatus"
    total = 0.0
    precio = 0.0
    for nodo in _criterios_raiz(entry, cfs):
        peso = _float(nodo, _CRITERIO_PESO_XPATH)
        if peso is None or peso < 0:
            continue
        total += peso
        if _es_criterio_precio(nodo):
            precio += peso
    if _PESO_TOTAL_PORCENTAJE[0] <= total <= _PESO_TOTAL_PORCENTAJE[1]:
        return round(precio, 4)
    if _PESO_TOTAL_FRACCION[0] <= total <= _PESO_TOTAL_FRACCION[1]:
        return round(precio * 100.0, 4)
    return None


def parse_lotes(
    entry: Any, licitacion_id: str, *, fallback_fecha_limite: str | None = None
) -> list[Lote]:
    """Extrae los lotes (``cac:ProcurementProjectLot``) de una entry CODICE.

    Cada lote anida su propio ``cac:ProcurementProject`` con la misma forma
    que el del expediente (título, CPV, presupuesto) -- patrón estándar UBL
    2.1 reutilizado por CODICE. Un lote sin ``cbc:ID`` se descarta: sin
    número no es direccionable (no hay a qué ``ProcurementProjectLotReference``
    de una adjudicación podría apuntar), así que persistirlo no aportaría nada
    verificable.

    Si el lote no publica su propio plazo de presentación, hereda
    ``fallback_fecha_limite`` (el del expediente, ya calculado por el
    llamador) -- la mayoría de expedientes con lotes comparten un único plazo
    para todos ellos.
    """
    cfs = "./cacext:ContractFolderStatus"
    lotes: list[Lote] = []
    for lot_elem in entry.xpath(f"{cfs}/cac:ProcurementProjectLot", namespaces=NS):
        numero = _text(lot_elem, "./cbc:ID")
        if not numero:
            continue
        pp = "./cac:ProcurementProject"
        titulo = _text(lot_elem, f"{pp}/cbc:Name")
        cpv = _text(
            lot_elem,
            f"{pp}/cac:RequiredCommodityClassification/cbc:ItemClassificationCode",
        )
        importe = _float(lot_elem, f"{pp}/cac:BudgetAmount/cbc:TaxExclusiveAmount")
        if importe is None:
            importe = _float(lot_elem, f"{pp}/cac:BudgetAmount/cbc:TotalAmount")
        fecha_limite = _tender_deadline(lot_elem, "./cac:TenderingProcess") or fallback_fecha_limite
        lotes.append(
            Lote(
                licitacion_id=licitacion_id,
                numero=numero,
                titulo=titulo,
                cpv=cpv,
                importe=importe,
                fecha_limite=fecha_limite,
            )
        )
    return lotes


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
    fecha_inicio = to_iso_date(_text(entry, f"{pp}/cbc:StartDate"))
    fecha_fin = to_iso_date(_text(entry, f"{pp}/cbc:EndDate"))
    fecha_limite = _tender_deadline(entry, f"{cfs}/cac:TenderingProcess")
    procedimiento, tramitacion = _tendering_process_codes(entry, f"{cfs}/cac:TenderingProcess")
    peso_precio_pct = parse_peso_precio(entry)

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

    lic = Licitacion(
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
        fecha_limite=fecha_limite,
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
        procedimiento=procedimiento,
        tramitacion=tramitacion,
        peso_precio_pct=peso_precio_pct,
    )

    # Track NULL % for critical fields (silent data loss detection)
    try:
        from observability.runtime_metrics import parser_entries_total, parser_field_null_total

        parser_entries_total.inc()
        _critical = {
            "organo_contratacion": lic.organo_contratacion,
            "importe": lic.importe,
            "cpv": lic.cpv,
            "estado": lic.estado,
            "fecha_publicacion": lic.fecha_publicacion,
            "fecha_limite": lic.fecha_limite,
            # No son campos críticos: son los tres candidatos a feature del
            # modelo de baja, y su NULL % ES la cobertura que decide si entran
            # en `FEATURE_COLUMNS` (umbral 50%). Instrumentarlos aquí mide esa
            # cobertura sobre el feed real sin escribir un script aparte.
            "procedimiento": lic.procedimiento,
            "tramitacion": lic.tramitacion,
            "peso_precio_pct": lic.peso_precio_pct,
        }
        for field, value in _critical.items():
            if value is None:
                parser_field_null_total.labels(field=field).inc()
    except Exception:
        pass

    return lic


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
    nuts_code = _text(entry, f"{project_xp}/cac:RealizedLocation/cbc:CountrySubentityCode")

    pp = f"{project_xp}/cac:PlannedPeriod"
    duracion_valor = _float(entry, f"{pp}/cbc:DurationMeasure")
    unit_attr = entry.xpath(f"{pp}/cbc:DurationMeasure/@unitCode", namespaces=NS)
    duracion_unidad = unit_attr[0] if unit_attr else None
    fecha_inicio = to_iso_date(_text(entry, f"{pp}/cbc:StartDate"))
    fecha_fin = to_iso_date(_text(entry, f"{pp}/cbc:EndDate"))
    fecha_limite = _tender_deadline(entry, f"{cfs}/cac:TenderingProcess")
    procedimiento, tramitacion = _tendering_process_codes(entry, f"{cfs}/cac:TenderingProcess")
    peso_precio_pct = parse_peso_precio(entry)
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
        fecha_limite=fecha_limite,
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
        procedimiento=procedimiento,
        tramitacion=tramitacion,
        peso_precio_pct=peso_precio_pct,
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
