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
from collections.abc import Iterable, Iterator
from typing import Any, NamedTuple

from lxml import etree

from config import settings
from db.database import (
    Adjudicacion,
    ClaseSolvencia,
    CondicionesCodice,
    CriterioAdjudicacion,
    DocumentoReferencia,
    GarantiaExigida,
    Licitacion,
    Lote,
    RequisitoSolvencia,
)
from observability.logging import get_logger
from scraper.puerta_tecnologica import MOTIVO_ADMITIDA, senal_tecnologica
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


# Dónde dice un `cac:TenderResult` a qué lote corresponde, en orden de
# preferencia. CODICE de PLACSP lo publica dentro del proyecto adjudicado
# (`AwardedTenderedProject/cbc:ProcurementProjectLotID`). La primera versión del
# parser solo leía la tercera forma —un wrapper "X + Reference" al estilo de las
# *DocumentReference— porque se escribió contra un fixture sintético, y en
# producción ninguna de las 1.619 adjudicaciones de expedientes multilote
# (medido el 2026-10-17) resolvió su lote. Se conservan las otras dos formas:
# leerlas no cuesta nada y un expediente que las use no debe perder el dato.
# No hace falta una cuarta: en los ZIP reales de 2026-06 a 2026-10, los 776
# `TenderResult` de las 295 entries multilote de los expedientes que seguían con
# adjudicaciones sin lote (medido el 2026-10-24) traen todos la primera forma
# (caso golden 19, real).
_XPATHS_LOTE_RESULTADO = (
    "./cac:AwardedTenderedProject/cbc:ProcurementProjectLotID",
    "./cac:AwardedTenderedProject/cac:ProcurementProjectLot/cbc:ID",
    "./cac:ProcurementProjectLotReference/cbc:ID",
)


def _lote_del_resultado(tr: Any) -> str | None:
    """Número del lote al que corresponde un ``cac:TenderResult``, o ``None``."""
    for xpath in _XPATHS_LOTE_RESULTADO:
        numero = _text(tr, xpath)
        if numero and numero.strip():
            return numero.strip()
    return None


def parse_adjudicaciones(entry: Any, licitacion_id: str) -> list[Adjudicacion]:
    """Extrae todas las adjudicaciones (TenderResult+WinningParty) de una entry."""
    cfs = "./cacext:ContractFolderStatus"
    results = entry.xpath(f"{cfs}/cac:TenderResult", namespaces=NS)
    out: list[Adjudicacion] = []
    for tr in results:
        result_code = _text(tr, "./cbc:ResultCode")
        result_desc = _text(tr, "./cbc:Description")
        # Ausente en expedientes de lote único -- lote_numero_raw queda None,
        # resuelto a lote_id=None (lote único implícito) en el punto de
        # persistencia. Ver `_lote_del_resultado` para las formas que se leen.
        lote_numero = _lote_del_resultado(tr)
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


def _tipos_anuncio(entry: Any, cfs: str) -> str | None:
    """``NoticeTypeCode`` de cada ``ValidNoticeInfo``: CSV de códigos crudos.

    Cada ``ValidNoticeInfo`` es un anuncio publicado (``DOC_CN`` licitación,
    ``DOC_CD`` pliegos, ``DOC_PIN_RTL`` información previa…). El parser ya leía
    su ``IssueDate`` (:func:`_issue_date`) y tiraba el código, así que no se
    podía saber si un expediente tuvo anuncio previo (spike T5). Se guardan los
    códigos **crudos**, distintos y ordenados: la lista oficial está versionada
    (``TenderingNoticeTypeCode-2.11.gc``) y traducirla aquí congelaría una
    copia. ``None`` si el expediente no publica ninguno.
    """
    codigos = entry.xpath(
        f"{cfs}/cacext:ValidNoticeInfo/cbcext:NoticeTypeCode/text()",
        namespaces=NS,
    )
    distintos = sorted({str(c).strip() for c in codigos if str(c).strip()})
    return ",".join(distintos) if distintos else None


#: Vocabulario de `licitaciones.importe_tipo` (ADR-032, D21).
TIPO_SIN_IVA = "sin_iva"
TIPO_CON_IVA = "con_iva"
TIPO_DESCONOCIDO = "desconocido"


class ImportesProyecto(NamedTuple):
    """Los tres importes de un proyecto CODICE, con la base declarada.

    Hasta 2026-09 el parser devolvía **un** número: `TaxExclusiveAmount` o, si
    faltaba, `TotalAmount`. El primero es la base sin IVA y el segundo lo
    incluye, y la fila no guardaba cuál de los dos había sido. `bajas` calculaba
    `(importe - adjudicado) / importe` sobre una mezcla de los dos, así que una
    baja del 21 % podía ser exactamente el IVA.

    `importe` se conserva como alias de la base sin IVA para no romper a los
    consumidores (frontend, exports, scoring, vistas materializadas); lo que
    cambia es que ahora viene acompañado de `tipo`.
    """

    importe: float | None
    base_sin_iva: float | None
    con_iva: float | None
    valor_estimado: float | None
    tipo: str | None


def _importes_del_proyecto(entry: Any, project_xp: str) -> ImportesProyecto:
    """Extrae los tres importes por separado y declara de cuál sale `importe`.

    El fallback a `TotalAmount` se conserva —una fila con importe con IVA es más
    útil que una sin importe— pero deja de ser invisible: `tipo` lo dice, y los
    cálculos comparativos filtran por él.
    """
    presupuesto = f"{project_xp}/cac:BudgetAmount"
    base_sin_iva = _float(entry, f"{presupuesto}/cbc:TaxExclusiveAmount")
    con_iva = _float(entry, f"{presupuesto}/cbc:TotalAmount")
    # El valor estimado incluye prórrogas y modificaciones: es el número con el
    # que la Ley 9/2017 determina el procedimiento, y no se extraía en absoluto.
    valor_estimado = _float(entry, f"{presupuesto}/cbc:EstimatedOverallContractAmount")

    if base_sin_iva is not None:
        return ImportesProyecto(base_sin_iva, base_sin_iva, con_iva, valor_estimado, TIPO_SIN_IVA)
    if con_iva is not None:
        return ImportesProyecto(con_iva, None, con_iva, valor_estimado, TIPO_CON_IVA)
    return ImportesProyecto(None, None, None, valor_estimado, None)


#: Un código DIR3 es una o dos letras seguidas de 7-8 dígitos: `E00003801`,
#: `L01280796`, `EA0003888`. El regex es la red para cuando CODICE publica el
#: identificador sin `schemeName`, que pasa.
_DIR3_RE = re.compile(r"^[A-Z]{1,2}[0-9]{7,8}$")


def _dir3_del_organo(entry: Any, cfs: str) -> str | None:
    """Código DIR3 del órgano de contratación, si CODICE lo publica (C1.2).

    DIR3 es el identificador oficial del Inventario de Unidades Orgánicas. Con
    él, dos grafías del mismo órgano son el mismo órgano sin discusión; sin él
    hay que resolver por nombre normalizado y aceptar que algunas fusiones las
    decide un humano.

    Se prefiere el identificador que declara su esquema (`schemeName` con
    "DIR3"); si no lo hay, se acepta cualquiera cuya **forma** sea la de un
    DIR3. Lo que no se hace es tomar el primer `PartyIdentification` que
    aparezca: en `LocatedContractingParty` puede venir un NIF, y confundir un
    NIF con un DIR3 crearía órganos fantasma con clave única.
    """
    base = f"{cfs}/cacext:LocatedContractingParty/cac:Party/cac:PartyIdentification"
    nodos = entry.xpath(f"{base}/cbc:ID", namespaces=NS)
    con_esquema: str | None = None
    por_forma: str | None = None
    for nodo in nodos:
        valor = (nodo.text or "").strip().upper()
        if not valor:
            continue
        esquema = (nodo.get("schemeName") or "").upper()
        if "DIR3" in esquema:
            con_esquema = con_esquema or valor
        elif _DIR3_RE.match(valor):
            por_forma = por_forma or valor
    return con_esquema or por_forma


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
# codifica en texto (UBL 2.1 / eForms usan `PRICE` y `COST`).
_TIPOS_CRITERIO_PRECIO = frozenset({"price", "cost"})

# CODICE de PLACSP lo codifica con una pareja tipo/subtipo. El tipo dice cómo se
# valora: `SUBJ` juicio de valor, `OBJ` fórmulas. El subtipo de `OBJ` dice qué:
# `1` precio, `2` otros criterios de fórmula «distintos del precio», `3`
# medioambientales, `4` sociales (los de `SUBJ` son `01`/`02`/`99`). La lista
# oficial no se ha podido leer (el host de la Plataforma está bloqueado desde el
# entorno de desarrollo); la lectura sale de cruzar los códigos con las
# descripciones de ~11 000 criterios en producción (2026-10-17).
#
# El código no siempre es fiable: hay órganos que codifican todas las partidas
# de fórmula como `OBJ`/`2`, el precio incluido; que ponen el `1` en una sola de
# varias «OFERTA ECONÓMICA» por producto, o en un criterio que no es el precio; o
# que publican la oferta económica como `SUBJ`. Por eso el código solo decide
# cuando la descripción no nombra el precio (ver `criterio_es_precio`).
_TIPO_CRITERIO_JUICIO = "SUBJ"
_TIPO_CRITERIO_FORMULA = "OBJ"
_SUBTIPO_CRITERIO_PRECIO = "1"

# Tokens (ya sin acentos y en minúscula) que identifican un criterio económico,
# para cuando el código no decide. Deliberadamente cortos y pocos: "economic"
# cubre económico/económica/economicos, y el conjunto se queda en lo que no
# admite otra lectura. Añadir "importe" o "baja" subiría el recall a costa de
# capturar criterios que no son el precio ("importe de la garantía", "baja
# temeraria" como umbral), y un peso del precio inflado es peor para el modelo
# que un NULL honesto.
_TOKENS_CRITERIO_PRECIO = ("precio", "economic", "coste")

# Menciones que nombran el precio para excluirlo. Es la etiqueta genérica de la
# categoría `OBJ`/`2` que muchos órganos copian como descripción («…mera
# aplicación de fórmulas, diferentes al precio»), y la de las mejoras que se
# ofrecen gratis («bolsa de horas sin coste»). Se borran del texto antes de
# buscar los tokens: «Oferta económica y criterios distintos del precio» sigue
# siendo el precio por "económica".
_MENCION_NEGADA_PRECIO = re.compile(
    r"\b(?:diferentes?|distinto|distinta|distintos|distintas)\s+"
    r"(?:(?:a|de)\s+)?(?:(?:al|del|el|la|los|las)\s+)?"
    r"(?:precio|coste|(?:propuesta|oferta|valoracion)\s+economica)"
    r"|\bno\s+relacionad[oa]s?\s+con\s+(?:el\s+)?(?:precio|coste)"
    r"|\bsin\s+(?:sobre)?costes?\b"
    r"|\bcoste\s+(?:cero|0)\b"
)

# Lo que hace falta para tomar un criterio de juicio de valor por el precio. En
# `SUBJ` "económica" o "coste" no bastan: «Gestión económica y contabilidad» o
# «Herramienta de gestión de costes» son módulos del software que se valora.
_PRECIO_EXPLICITO = re.compile(r"\b(?:oferta|propuesta|proposicion)\s+economica|\bprecios?\b")

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
_CRITERIO_SUBTIPO_XPATH = (
    "./*[local-name()='AwardingCriteriaSubTypeCode' or local-name()='AwardingCriterionSubTypeCode']"
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


def _codigos_normalizados(tipo: str | None, subtipo: str | None) -> tuple[str, str]:
    """Tipo en mayúsculas y subtipo, sin espacios y como cadena vacía si faltan."""
    return (tipo or "").strip().upper(), (subtipo or "").strip()


def criterio_es_precio(tipo: str | None, subtipo: str | None, texto: str | None) -> bool:
    """¿Es este criterio el precio?

    Por orden:

    1. El tipo textual de UBL 2.1 (``PRICE``/``COST``) lo es.
    2. Un juicio de valor (``SUBJ``) solo si la descripción lo dice expresamente
       (:data:`_PRECIO_EXPLICITO`): el precio se valora por fórmula (art. 146
       LCSP), pero hay órganos que publican así la oferta económica.
    3. Si la descripción, sin las menciones que niegan el precio, lo nombra, lo
       es, diga lo que diga el subtipo.
    4. Si la descripción calla («…mera aplicación de fórmulas.»), decide el
       código: ``OBJ``/``1``.

    Trabaja sobre valores y no sobre el XML porque es la misma regla que aplica
    ``scripts/backfill_criterio_precio.py`` a las filas ya guardadas.
    """
    tipo, subtipo = _codigos_normalizados(tipo, subtipo)
    if tipo.lower() in _TIPOS_CRITERIO_PRECIO:
        return True
    plano = _MENCION_NEGADA_PRECIO.sub(" ", _sin_acentos(texto or ""))
    if tipo == _TIPO_CRITERIO_JUICIO:
        return _PRECIO_EXPLICITO.search(plano) is not None
    if any(token in plano for token in _TOKENS_CRITERIO_PRECIO):
        return True
    return tipo == _TIPO_CRITERIO_FORMULA and subtipo == _SUBTIPO_CRITERIO_PRECIO


def peso_precio_de_criterios(criterios: Iterable[tuple[float | None, bool]]) -> float | None:
    """Peso del precio en % sobre 100 a partir de los criterios raíz.

    ``criterios`` son parejas (peso publicado, es el precio). La regla de la
    escala está en :func:`parse_peso_precio`; vive aquí, sobre valores, para
    que el backfill la aplique igual a las filas guardadas.
    """
    total = 0.0
    precio = 0.0
    for peso, es_precio in criterios:
        if peso is None or peso < 0:
            continue
        total += peso
        if es_precio:
            precio += peso
    if _PESO_TOTAL_PORCENTAJE[0] <= total <= _PESO_TOTAL_PORCENTAJE[1]:
        return round(precio, 4)
    if _PESO_TOTAL_FRACCION[0] <= total <= _PESO_TOTAL_FRACCION[1]:
        return round(precio * 100.0, 4)
    return None


def _codigos_criterio(nodo: Any) -> tuple[str | None, str | None]:
    return _text(nodo, _CRITERIO_TIPO_XPATH), _text(nodo, _CRITERIO_SUBTIPO_XPATH)


def _es_criterio_precio(nodo: Any) -> bool:
    textos = nodo.xpath(_CRITERIO_TEXTO_XPATH, namespaces=NS)
    return criterio_es_precio(*_codigos_criterio(nodo), " ".join(str(t) for t in textos))


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
    return peso_precio_de_criterios(
        (_float(nodo, _CRITERIO_PESO_XPATH), _es_criterio_precio(nodo))
        for nodo in _criterios_raiz(entry, cfs)
    )


# ── Condiciones oficiales: criterios, garantías y solvencia (v148) ───────────
#
# Los nombres de elemento se buscan por `local-name()`, como los criterios de
# arriba: el feed mezcla expedientes publicados con el esquema CODICE
# (`...Criteria`) y con la grafía de UBL 2.1 (`...Criterion`), y el prefijo de
# namespace de cada uno no aporta nada a la lectura.

#: Contenedores de un criterio de adjudicación: el de primer nivel y el
#: anidado, en las dos grafías. Un nodo con uno de estos nombres es un
#: criterio; cualquier otro hijo de ``AwardingTerms`` (o de un criterio) es un
#: campo o un envoltorio, y se recorre buscando criterios dentro.
_CRITERIO_CONTENEDORES = frozenset(
    {
        "AwardingCriteria",
        "AwardingCriterion",
        "SubordinateAwardingCriteria",
        "SubordinateAwardingCriterion",
    }
)

_SOLVENCIA_POR_ELEMENTO: dict[str, ClaseSolvencia] = {
    "TechnicalEvaluationCriteria": "tecnica",
    "TechnicalEvaluationCriterion": "tecnica",
    "FinancialEvaluationCriteria": "economica",
    "FinancialEvaluationCriterion": "economica",
}


def _hijo(*nombres: str) -> str:
    """XPath de un hijo directo por nombre local, en cualquier namespace."""
    condicion = " or ".join(f"local-name()='{nombre}'" for nombre in nombres)
    return f"./*[{condicion}]"


def _moneda(nodo: Any, nombre: str) -> str | None:
    valores = nodo.xpath(f"{_hijo(nombre)}/@currencyID")
    if not valores:
        return None
    return str(valores[0]).strip() or None


def _es_elemento(nodo: Any) -> bool:
    """Descarta comentarios e instrucciones de proceso, que lxml también itera."""
    return isinstance(nodo.tag, str)


def _escala_pct(pesos_raiz: list[float]) -> float | None:
    """Factor que lleva un peso de este ámbito a % sobre 100, o ``None``.

    La misma regla que ``parse_peso_precio``: la suma de los criterios raíz
    declara la escala (≈100 porcentajes, ≈1 fracciones); fuera de ambas bandas
    no se puede afirmar y ningún criterio del ámbito lleva porcentaje.
    """
    total = sum(p for p in pesos_raiz if p >= 0)
    if _PESO_TOTAL_PORCENTAJE[0] <= total <= _PESO_TOTAL_PORCENTAJE[1]:
        return 1.0
    if _PESO_TOTAL_FRACCION[0] <= total <= _PESO_TOTAL_FRACCION[1]:
        return 100.0
    return None


def _criterios_del_ambito(
    bloques: list[Any], lote_numero: str | None
) -> list[CriterioAdjudicacion]:
    """Criterios de un ámbito, en orden de documento, con su padre.

    ``bloques`` son los ``TenderingTerms`` del ámbito (normalmente uno). Se
    numeran seguidos: si el anuncio repite el bloque, o dos lotes comparten
    número, ``orden`` no vuelve a empezar y la unicidad
    ``(licitacion_id, lote_numero, orden)`` de v148 se sostiene.

    Se recorre el árbol en vez de pedir los nodos con ``//`` porque lo que
    importa de un subcriterio es **de quién** es: el padre es el criterio más
    cercano por encima. Un criterio vacío (sin descripción, peso, tipo ni nota)
    no se guarda; si tenía hijos, estos suben a su abuelo.
    """
    crudos: list[tuple[Any, int | None]] = []

    def recorrer(nodo: Any, padre: int | None) -> None:
        for hijo in nodo:
            if not _es_elemento(hijo):
                continue
            if etree.QName(hijo).localname in _CRITERIO_CONTENEDORES:
                crudos.append((hijo, padre))
                recorrer(hijo, len(crudos) - 1)
            else:
                recorrer(hijo, padre)

    for terms in bloques:
        for awarding_terms in terms.xpath(_hijo("AwardingTerms")):
            recorrer(awarding_terms, None)

    leidos: list[CriterioAdjudicacion] = []
    #: Índice crudo → orden asignado, solo para los criterios que se guardan.
    orden_por_indice: dict[int, int] = {}
    #: Índice crudo de un descartado → su antepasado guardado más cercano.
    heredado: dict[int, int | None] = {}
    for indice, (nodo, padre) in enumerate(crudos):
        # Si el padre se descartó, el ancestro es el que heredó el descartado.
        ancestro = padre if padre is None or padre in orden_por_indice else heredado.get(padre)
        criterio = CriterioAdjudicacion(
            orden=0,
            lote_numero=lote_numero,
            descripcion=_text(nodo, _hijo("Description", "Name")),
            peso=_float(nodo, _CRITERIO_PESO_XPATH),
            tipo_codigo=_text(nodo, _CRITERIO_TIPO_XPATH),
            subtipo_codigo=_text(
                nodo, _hijo("AwardingCriteriaSubTypeCode", "AwardingCriterionSubTypeCode")
            ),
            nota=_text(nodo, _hijo("Note")),
        )
        vacio = not any(
            (
                criterio.descripcion,
                criterio.peso is not None,
                criterio.tipo_codigo,
                criterio.subtipo_codigo,
                criterio.nota,
            )
        )
        if vacio:
            heredado[indice] = ancestro
            continue
        criterio.orden = len(leidos) + 1
        criterio.padre_orden = orden_por_indice[ancestro] if ancestro is not None else None
        criterio.es_precio = _es_criterio_precio(nodo)
        orden_por_indice[indice] = criterio.orden
        leidos.append(criterio)

    raiz = [c for c in leidos if c.padre_orden is None]
    factor = _escala_pct([c.peso for c in raiz if c.peso is not None])
    if factor is not None:
        for criterio in raiz:
            if criterio.peso is not None and criterio.peso >= 0:
                criterio.peso_pct = round(criterio.peso * factor, 4)
    return leidos


def _garantias_del_ambito(bloques: list[Any], lote_numero: str | None) -> list[GarantiaExigida]:
    garantias: list[GarantiaExigida] = []
    nodos = [n for terms in bloques for n in terms.xpath(_hijo("RequiredFinancialGuarantee"))]
    for nodo in nodos:
        garantia = GarantiaExigida(
            orden=len(garantias) + 1,
            lote_numero=lote_numero,
            tipo_codigo=_text(nodo, _hijo("GuaranteeTypeCode")),
            porcentaje=_float(nodo, _hijo("AmountRate")),
            importe=_float(nodo, _hijo("LiabilityAmount")),
            moneda=_moneda(nodo, "LiabilityAmount"),
            descripcion=_text(nodo, _hijo("Description")),
        )
        if (
            garantia.tipo_codigo is None
            and garantia.porcentaje is None
            and garantia.importe is None
            and garantia.descripcion is None
        ):
            continue
        garantias.append(garantia)
    return garantias


def _umbral_de_solvencia(nodo: Any, clase: ClaseSolvencia) -> tuple[float | None, str | None]:
    """Umbral en importe de un requisito de solvencia, con su moneda.

    El esquema UBL lo llama ``ThresholdAmount`` (con ``currencyID``), pero
    PLACSP no lo publica nunca: medido sobre 3.903 entradas del ATOM vivo
    (2026-10-24), el umbral viaja en ``cbc:ThresholdQuantity``, sin moneda.

    En la solvencia **económica** esa cantidad es dinero en todos los códigos
    observados (volumen de negocios, seguro de responsabilidad, patrimonio
    neto), así que se guarda como importe. En la **técnica** no: el mismo
    código ``OSR-COMPTASK`` trae unas veces el importe de los trabajos
    similares (179.384,97) y otras el número de trabajos («al menos dos
    obras» → 2); leerla como euros pintaría «Umbral 2 €». Se queda fuera
    hasta que haya columna para una cantidad que no es importe.

    Un ``0`` es «no se exige cifra» (lo publican con descripciones como
    «Exento.»), no un umbral de cero euros: se trata como ausente.
    """
    importe = _float(nodo, _hijo("ThresholdAmount"))
    if importe is not None:
        return importe, _moneda(nodo, "ThresholdAmount")
    if clase != "economica":
        return None, None
    cantidad = _float(nodo, _hijo("ThresholdQuantity"))
    if cantidad is None or cantidad <= 0:
        return None, None
    return cantidad, None


def _solvencia_del_ambito(bloques: list[Any], lote_numero: str | None) -> list[RequisitoSolvencia]:
    requisitos: list[RequisitoSolvencia] = []

    def anadir(clase: ClaseSolvencia, **campos: Any) -> None:
        requisitos.append(
            RequisitoSolvencia(
                orden=len(requisitos) + 1, clase=clase, lote_numero=lote_numero, **campos
            )
        )

    peticiones = [
        p for terms in bloques for p in terms.xpath(_hijo("TendererQualificationRequest"))
    ]
    for peticion in peticiones:
        for hijo in peticion:
            if not _es_elemento(hijo):
                continue
            local = etree.QName(hijo).localname
            clase = _SOLVENCIA_POR_ELEMENTO.get(local)
            if clase is not None:
                tipo = _text(
                    hijo, _hijo("EvaluationCriteriaTypeCode", "EvaluationCriterionTypeCode")
                )
                descripcion = _text(hijo, _hijo("Description"))
                umbral, moneda = _umbral_de_solvencia(hijo, clase)
                if tipo is None and descripcion is None and umbral is None:
                    continue
                anadir(
                    clase,
                    tipo_codigo=tipo,
                    descripcion=descripcion,
                    umbral_importe=umbral,
                    moneda=moneda,
                )
            elif local == "RequiredBusinessClassificationScheme":
                for categoria in hijo.xpath(".//*[local-name()='ClassificationCategory']"):
                    codigo = _text(categoria, _hijo("CodeValue"))
                    nombre = _text(categoria, _hijo("Name", "Description"))
                    if codigo is None and nombre is None:
                        continue
                    anadir("clasificacion", tipo_codigo=codigo, descripcion=nombre)
    return requisitos


def parse_condiciones(entry: Any) -> CondicionesCodice:
    """Criterios, garantías y solvencia de ``cac:TenderingTerms`` (v148).

    Lee el bloque del expediente (``ContractFolderStatus/cac:TenderingTerms``)
    y el de cada lote con número (``cac:ProcurementProjectLot/cac:TenderingTerms``),
    y devuelve las tres familias aplanadas con ``lote_numero`` para distinguir
    el ámbito (``None`` = expediente). Un lote sin ``cbc:ID`` se ignora por lo
    mismo que en :func:`parse_lotes`: no hay a qué lote atribuirlo.

    **Qué se guarda crudo y por qué.** Los códigos (`AwardingCriteriaTypeCode`,
    `GuaranteeTypeCode`, `EvaluationCriteriaTypeCode`, la categoría de
    clasificación) van tal cual: sus listas controladas no se han podido
    verificar contra el servidor de la Plataforma, y traducirlas de memoria
    convertiría un código en una etiqueta plausible pero falsa (el criterio de
    ``shared/procedimientos.py``). La UI enseña descripción, peso e importe,
    que no necesitan lista. La única lectura de código que se hace es la del
    criterio del precio (``OBJ``/``1``, ver ``_es_criterio_precio``), que se
    contrastó con las descripciones publicadas, y se guarda aparte en
    ``es_precio``: los códigos siguen viajando crudos.

    **Nombres verificados contra el feed** (``scripts/medir_terminos_codice.py``
    sobre 3.903 entradas del ATOM vivo, 2026-10-24): los criterios van en
    ``cac:AwardingTerms/cac:AwardingCriteria`` (``AwardingCriteriaTypeCode``,
    ``AwardingCriteriaSubTypeCode``, ``Description``, ``WeightNumeric``,
    ``Note``), sin subcriterios anidados; la garantía en
    ``cac:RequiredFinancialGuarantee`` (``GuaranteeTypeCode``, ``AmountRate``
    en porcentaje —5 = 5 %—, ``LiabilityAmount``), solo a nivel de
    expediente; la solvencia en ``cac:TendererQualificationRequest`` con
    ``Technical``/``FinancialEvaluationCriteria`` y
    ``RequiredBusinessClassificationScheme`` (solo ``CodeValue``, sin
    nombre). El umbral no es ``ThresholdAmount`` sino ``ThresholdQuantity``:
    ver :func:`_umbral_de_solvencia`. ``SpecificTendererRequirement`` (las
    declaraciones responsables: capacidad de obrar, no prohibición…) no se
    lee: no es solvencia. La grafía UBL 2.1 (``...Criterion``) no apareció en
    la muestra y se sigue aceptando. ``parser_field_null_total`` cuenta en
    producción las tres familias con los campos ``criterios_adjudicacion``,
    ``garantias`` y ``solvencia``.
    """
    cfs = "./cacext:ContractFolderStatus"
    condiciones = CondicionesCodice()
    # Bloques agrupados por ámbito, expediente primero y lotes en orden de
    # aparición. Agrupar (y no tratar cada bloque por separado) es lo que
    # mantiene `orden` único dentro de cada ámbito.
    ambitos: dict[str | None, list[Any]] = {
        None: list(entry.xpath(f"{cfs}/cac:TenderingTerms", namespaces=NS))
    }
    for lot_elem in entry.xpath(f"{cfs}/cac:ProcurementProjectLot", namespaces=NS):
        numero = _text(lot_elem, "./cbc:ID")
        if not numero:
            continue
        ambitos.setdefault(numero, []).extend(lot_elem.xpath("./cac:TenderingTerms", namespaces=NS))
    for lote_numero, bloques in ambitos.items():
        condiciones.criterios.extend(_criterios_del_ambito(bloques, lote_numero))
        condiciones.garantias.extend(_garantias_del_ambito(bloques, lote_numero))
        condiciones.solvencia.extend(_solvencia_del_ambito(bloques, lote_numero))
    return condiciones


def _condiciones_o_none(entry: Any) -> CondicionesCodice | None:
    """:func:`parse_condiciones` sin poder tumbar el parseo de la entry.

    Es un añadido: una entry que se parseaba antes de v148 tiene que seguir
    parseándose aunque su ``TenderingTerms`` traiga algo que este código no
    espera. ``None`` le dice al upsert que no toque lo que ya hubiera.
    """
    try:
        return parse_condiciones(entry)
    except Exception as exc:
        log.warning("codice_condiciones_parse_error", error=str(exc))
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


def _cpvs_del_proyecto(entry: Any, project_xp: str) -> list[str]:
    """Todos los CPV del proyecto, no solo el primero que guarda `cpv`."""
    codigos = entry.xpath(
        f"{project_xp}/cac:RequiredCommodityClassification/cbc:ItemClassificationCode/text()",
        namespaces=NS,
    )
    return [str(c).strip() for c in codigos if str(c).strip()]


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
    organo_dir3 = _dir3_del_organo(entry, cfs)

    project_xp = f"{cfs}/cac:ProcurementProject"
    nombre_proyecto = _text(entry, f"{project_xp}/cbc:Name")
    tipo = _text(entry, f"{project_xp}/cbc:TypeCode")
    cpv = _text(
        entry,
        f"{project_xp}/cac:RequiredCommodityClassification/cbc:ItemClassificationCode",
    )
    # C1.1 / ADR-032: los tres importes por separado, con la base declarada.
    importes = _importes_del_proyecto(entry, project_xp)
    importe = importes.importe
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

    # Decide el título, con la misma puerta que PSCP (2026-09-27). El `summary`
    # ya no entra: en PLACSP es «Id; Órgano; Importe; Estado», y el nombre del
    # órgano hacía de keyword (una limpieza del Instituto Nacional de
    # Ciberseguridad salía CIBERSEGURIDAD). Las keywords ambiguas necesitan que
    # algún CPV del proyecto las corrobore, y se miran todos, no solo el primero.
    # Lo que no entra por keyword sigue su camino por el CPV
    # (`scraper.pipeline`), como antes.
    senal = senal_tecnologica(titulo, " ".join(_cpvs_del_proyecto(entry, project_xp)))
    if senal.motivo != MOTIVO_ADMITIDA:
        return None
    tecnologias = list(senal.tecnologias)
    kw = list(senal.keywords)

    fecha_pub = _issue_date(entry, cfs) or fecha_upd

    lic = Licitacion(
        id_externo=id_externo,
        titulo=titulo or "(sin título)",
        descripcion=summary,
        organo_contratacion=organo_codice or s.get("organo_contratacion"),
        organo_dir3=organo_dir3,
        importe=importe if importe is not None else s.get("importe"),
        importe_base_sin_iva=importes.base_sin_iva,
        importe_con_iva=importes.con_iva,
        valor_estimado=importes.valor_estimado,
        importe_tipo=importes.tipo,
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
        tipos_anuncio=_tipos_anuncio(entry, cfs),
        condiciones=_condiciones_o_none(entry),
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
            # v148: cobertura de cada familia de `cac:TenderingTerms`. Una
            # lista vacía cuenta como NULL: es «este anuncio no lo trae».
            "criterios_adjudicacion": (lic.condiciones.criterios or None)
            if lic.condiciones
            else None,
            "garantias": (lic.condiciones.garantias or None) if lic.condiciones else None,
            "solvencia": (lic.condiciones.solvencia or None) if lic.condiciones else None,
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
    organo_dir3 = _dir3_del_organo(entry, cfs)

    project_xp = f"{cfs}/cac:ProcurementProject"
    nombre_proyecto = _text(entry, f"{project_xp}/cbc:Name")
    tipo = _text(entry, f"{project_xp}/cbc:TypeCode")
    cpv = _text(
        entry,
        f"{project_xp}/cac:RequiredCommodityClassification/cbc:ItemClassificationCode",
    )
    # C1.1 / ADR-032: los tres importes por separado, con la base declarada.
    importes = _importes_del_proyecto(entry, project_xp)
    importe = importes.importe
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
        organo_dir3=organo_dir3,
        importe=importe if importe is not None else s.get("importe"),
        importe_base_sin_iva=importes.base_sin_iva,
        importe_con_iva=importes.con_iva,
        valor_estimado=importes.valor_estimado,
        importe_tipo=importes.tipo,
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
        tipos_anuncio=_tipos_anuncio(entry, cfs),
        condiciones=_condiciones_o_none(entry),
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
