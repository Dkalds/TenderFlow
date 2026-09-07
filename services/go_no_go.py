"""Contraste entre la ficha del pliego y la capacidad declarada (S2.3).

La ficha (``shared/tender_facts.py``) sabe qué exige el pliego y con qué cita
lo exige. El perfil de capacidad (S2.2) sabe qué puede acreditar la
organización. Este módulo cruza lo uno con lo otro y responde, por requisito,
``cumple | no_cumple | desconocido``.

Tres reglas que no se negocian, porque son la diferencia entre ayudar a decidir
y decidir por alguien:

1. **Ningún ``cumple`` sin ``EvidenceRef``.** Si el hecho del pliego llega sin
   cita, el veredicto baja a ``desconocido`` aunque el dato de la organización
   encaje: afirmar que se cumple un requisito que nadie puede ir a leer al PDF
   es exactamente el tipo de dato fabricado que este producto no publica.
2. **``desconocido`` es una respuesta de primera.** Se contesta cuando la ficha
   no extrajo el hecho *o* cuando la organización no rellenó el campo. No hay
   valor por defecto optimista ni pesimista: no saber se dice.
3. **Esto no cierra nada.** El resultado es una propuesta para la pestaña
   Decisión; quien marca go/no-go es una persona.

El golden ``tests/fixtures/golden_go_no_go.jsonl`` fija el veredicto esperado
por familia en diez fichas escritas a mano. Está escrito a mano **a propósito**:
un golden generado desde la salida de este módulo solo probaría que el módulo
hace lo que hace.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from db.repositories.organization_capabilities import (
    OrganizationCapabilitiesRepository,
    seal_checklist_evaluated,
)
from db.repositories.pursuits import PursuitRepository
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
from observability.logging import get_logger
from services.normalization import fold_text
from services.organizations import resolve_organization
from shared.dto import (
    OrganizationCapabilities,
    OrganizationCertification,
    OrganizationReferencia,
    OrganizationTeamProfile,
)
from shared.tender_facts import (
    CertificationRequirement,
    EvidenceRef,
    FactItem,
    TeamRequirement,
    TenderFactSheet,
    TenderFactSheetRecord,
)

log = get_logger(__name__)

_capabilities_repo = OrganizationCapabilitiesRepository()
_pursuit_repo = PursuitRepository()
_fact_sheets_repo = TenderFactSheetsRepository()

ChecklistVeredicto = Literal["cumple", "no_cumple", "desconocido"]

#: Las cuatro familias de ``TenderFactSheet`` que el perfil de capacidad puede
#: contrastar. Las demás (lotes, criterios, plazos…) describen el expediente,
#: no un requisito que la organización acredite o deje de acreditar.
ChecklistFamilia = Literal[
    "certifications",
    "economic_solvency",
    "technical_solvency",
    "team_requirements",
]

_FAMILIAS: tuple[ChecklistFamilia, ...] = (
    "certifications",
    "economic_solvency",
    "technical_solvency",
    "team_requirements",
)

_ETIQUETAS: dict[ChecklistFamilia, str] = {
    "certifications": "Certificaciones",
    "economic_solvency": "Solvencia económica",
    "technical_solvency": "Solvencia técnica",
    "team_requirements": "Equipo requerido",
}

_SIN_EVIDENCIA = (
    "El pliego exige este requisito pero la ficha no trae ninguna cita "
    "verificable, así que no se afirma que se cumpla."
)


class ChecklistItem(BaseModel):
    """Un requisito del pliego contrastado con el perfil de la organización."""

    model_config = ConfigDict(extra="forbid")

    familia: ChecklistFamilia
    #: El requisito tal y como lo describe la ficha, para que quien lee el
    #: veredicto vea contra qué se contrastó sin abrir el pliego.
    requisito: str
    veredicto: ChecklistVeredicto
    #: Por qué ese veredicto, en castellano y citando el dato que lo decide.
    motivo: str
    #: Citas del pliego. Vacía obliga a ``desconocido`` (regla 1 del módulo).
    evidencia: list[EvidenceRef] = Field(default_factory=list)
    #: Qué dato del perfil se usó, o ``None`` si no había ninguno que usar.
    dato_organizacion: str | None = None


class ChecklistFamiliaResultado(BaseModel):
    """Veredicto agregado de una familia y los requisitos que lo componen."""

    model_config = ConfigDict(extra="forbid")

    familia: ChecklistFamilia
    etiqueta: str
    #: El peor de sus ítems: ``no_cumple`` > ``desconocido`` > ``cumple``. Una
    #: familia con un requisito incumplido no es «casi cumple».
    veredicto: ChecklistVeredicto
    items: list[ChecklistItem] = Field(default_factory=list)


class GoNoGoChecklist(BaseModel):
    """Contraste completo de una oportunidad contra la capacidad declarada."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    organization_id: int = Field(ge=1)
    #: Estado de la ficha (``pending``, ``extracted``…) o ``None`` si no hay
    #: ficha todavía. Sin ficha, las cuatro familias son ``desconocido`` y esto
    #: es lo que lo explica.
    ficha_estado: str | None = None
    #: Versión del extractor que produjo la ficha evaluada. Que viaje en la
    #: respuesta es lo que permite saber si un veredicto guardado ayer se
    #: calculó sobre la misma ficha que el de hoy.
    extraction_version: str | None = None
    #: Fecha de la ficha evaluada (``updated_at`` de ``tender_fact_sheets``).
    ficha_actualizada: str | None = None
    familias: list[ChecklistFamiliaResultado] = Field(default_factory=list)
    total_requisitos: int = Field(default=0, ge=0)
    cumple: int = Field(default=0, ge=0)
    no_cumple: int = Field(default=0, ge=0)
    desconocido: int = Field(default=0, ge=0)


class ChecklistNotFoundError(LookupError):
    """La oportunidad no existe dentro de la organización del solicitante."""


# ── Utilidades de comparación ──────────────────────────────────────────────


def _contiene(texto: str, aguja: str) -> bool:
    """¿Aparece ``aguja`` en ``texto``, ignorando tildes y mayúsculas?

    Coincidencia por contención en las dos direcciones (la hace el llamador):
    el pliego escribe «certificado ISO 27001 vigente» y la organización
    declara «ISO 27001». Exigir igualdad exacta no casaría ninguna de las dos.
    """
    aguja_plegada = fold_text(aguja).strip()
    if not aguja_plegada:
        return False
    return aguja_plegada in fold_text(texto)


# Importes en castellano: "1.200.000 €", "300.000,00 euros", "50000 EUR".
# El separador de miles es el punto y el decimal la coma, así que el orden de
# los reemplazos importa.
_IMPORTE_RE = re.compile(
    r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(?:€|eur\b|euros\b)",
    flags=re.IGNORECASE,
)


def _importe_en_texto(texto: str) -> float | None:
    """El umbral en euros que menciona un requisito, o ``None``.

    Se queda con el **mayor** de los importes citados: cuando un requisito
    menciona varios (por lotes, o por anualidad y total), el que decide si se
    puede concurrir es el más alto. Quedarse con el primero haría depender el
    veredicto del orden en que el extractor los escribió.
    """
    valores: list[float] = []
    for match in _IMPORTE_RE.finditer(texto):
        crudo = match.group(1).replace(".", "").replace(",", ".")
        try:
            valores.append(float(crudo))
        except ValueError:  # pragma: no cover - el regex ya acota la forma
            continue
    return max(valores) if valores else None


def _eur(valor: float) -> str:
    return f"{valor:,.0f} €".replace(",", ".")


def _con_evidencia(
    familia: ChecklistFamilia,
    requisito: str,
    *,
    evidencia: list[EvidenceRef],
    motivo: str,
    dato: str | None,
) -> ChecklistItem:
    """``cumple`` solo si hay cita; si no, ``desconocido`` diciendo por qué."""
    if not evidencia:
        return ChecklistItem(
            familia=familia,
            requisito=requisito,
            veredicto="desconocido",
            motivo=_SIN_EVIDENCIA,
            evidencia=[],
            dato_organizacion=dato,
        )
    return ChecklistItem(
        familia=familia,
        requisito=requisito,
        veredicto="cumple",
        motivo=motivo,
        evidencia=evidencia,
        dato_organizacion=dato,
    )


# ── Reglas por familia ─────────────────────────────────────────────────────


def _certificacion_que_encaja(
    requisito: CertificationRequirement,
    declaradas: list[OrganizationCertification],
) -> OrganizationCertification | None:
    """La certificación declarada que responde al requisito, si alguna.

    El ámbito del pliego acota: una certificación de empresa no acredita un
    título personal exigido al equipo. ``other`` en el pliego significa «no se
    sabe de quién», así que no descarta nada.
    """
    for cert in declaradas:
        if requisito.scope != "other" and cert.ambito != requisito.scope:
            continue
        if _contiene(requisito.name, cert.nombre) or _contiene(cert.nombre, requisito.name):
            return cert
    return None


def _evaluar_certificaciones(
    facts: TenderFactSheet,
    capacidad: OrganizationCapabilities,
    hoy: date,
) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    for requisito in facts.certifications:
        if not capacidad.certificaciones:
            items.append(
                ChecklistItem(
                    familia="certifications",
                    requisito=requisito.name,
                    veredicto="desconocido",
                    motivo="La organización no ha declarado ninguna certificación.",
                    evidencia=list(requisito.evidence),
                )
            )
            continue
        encaje = _certificacion_que_encaja(requisito, capacidad.certificaciones)
        if encaje is None:
            items.append(
                ChecklistItem(
                    familia="certifications",
                    requisito=requisito.name,
                    veredicto="no_cumple",
                    motivo=(
                        "Ninguna de las certificaciones declaradas corresponde a "
                        f"«{requisito.name}»."
                    ),
                    evidencia=list(requisito.evidence),
                )
            )
            continue
        if encaje.vigente_hasta is not None and encaje.vigente_hasta < hoy:
            items.append(
                ChecklistItem(
                    familia="certifications",
                    requisito=requisito.name,
                    veredicto="no_cumple",
                    motivo=(
                        f"«{encaje.nombre}» está declarada pero caducó el "
                        f"{encaje.vigente_hasta.isoformat()}."
                    ),
                    evidencia=list(requisito.evidence),
                    dato_organizacion=encaje.nombre,
                )
            )
            continue
        vigencia = (
            "sin fecha de caducidad declarada"
            if encaje.vigente_hasta is None
            else f"vigente hasta {encaje.vigente_hasta.isoformat()}"
        )
        items.append(
            _con_evidencia(
                "certifications",
                requisito.name,
                evidencia=list(requisito.evidence),
                motivo=f"La organización declara «{encaje.nombre}» ({vigencia}).",
                dato=encaje.nombre,
            )
        )
    return items


def _evaluar_solvencia_economica(
    facts: TenderFactSheet,
    capacidad: OrganizationCapabilities,
) -> list[ChecklistItem]:
    # La LCSP mide el volumen anual de negocio por el **mejor** de los tres
    # últimos ejercicios, así que el contraste es contra el máximo declarado y
    # no contra la media ni el último año.
    mejor = max((f.importe_eur for f in capacidad.facturacion), default=None)
    mejor_ejercicio = (
        max(capacidad.facturacion, key=lambda f: f.importe_eur).ejercicio
        if capacidad.facturacion
        else None
    )
    items: list[ChecklistItem] = []
    for requisito in facts.economic_solvency:
        if mejor is None or mejor_ejercicio is None:
            items.append(
                ChecklistItem(
                    familia="economic_solvency",
                    requisito=requisito.description,
                    veredicto="desconocido",
                    motivo="La organización no ha declarado su facturación anual.",
                    evidencia=list(requisito.evidence),
                )
            )
            continue
        umbral = requisito.amount_eur
        if umbral is None:
            umbral = _importe_en_texto(requisito.description)
        if umbral is None:
            items.append(
                ChecklistItem(
                    familia="economic_solvency",
                    requisito=requisito.description,
                    veredicto="desconocido",
                    motivo=(
                        "El pliego no cifra un umbral que se pueda comparar con la "
                        "facturación declarada."
                    ),
                    evidencia=list(requisito.evidence),
                    dato_organizacion=f"{_eur(mejor)} en {mejor_ejercicio}",
                )
            )
            continue
        dato = f"{_eur(mejor)} en {mejor_ejercicio}"
        if mejor >= umbral:
            items.append(
                _con_evidencia(
                    "economic_solvency",
                    requisito.description,
                    evidencia=list(requisito.evidence),
                    motivo=(
                        f"El mejor ejercicio declarado ({dato}) alcanza el umbral de "
                        f"{_eur(umbral)}."
                    ),
                    dato=dato,
                )
            )
            continue
        items.append(
            ChecklistItem(
                familia="economic_solvency",
                requisito=requisito.description,
                veredicto="no_cumple",
                motivo=(
                    f"El mejor ejercicio declarado ({dato}) no llega al umbral de {_eur(umbral)}."
                ),
                evidencia=list(requisito.evidence),
                dato_organizacion=dato,
            )
        )
    return items


def _referencia_por_tecnologia(
    requisito: FactItem,
    referencias: list[OrganizationReferencia],
) -> OrganizationReferencia | None:
    for referencia in referencias:
        if referencia.tecnologia and _contiene(requisito.description, referencia.tecnologia):
            return referencia
    return None


def _evaluar_solvencia_tecnica(
    facts: TenderFactSheet,
    capacidad: OrganizationCapabilities,
) -> list[ChecklistItem]:
    """Contrasta cada requisito técnico contra las referencias declaradas.

    Dos caminos, y solo dos, porque son los que se pueden defender:

    * **Con importe en el requisito** («contratos similares por importe igual o
      superior a X»): se compara con la mejor referencia que declare importe.
    * **Sin importe**: se busca que alguna referencia sea de la tecnología que
      el requisito nombra. Si el requisito no nombra ninguna que la
      organización tenga, el veredicto es ``desconocido`` y no ``no_cumple``:
      que este código no sepa casar un texto libre no es prueba de que la
      organización no pueda acreditarlo.
    """
    items: list[ChecklistItem] = []
    con_importe = [r for r in capacidad.referencias if r.importe_eur is not None]
    for requisito in facts.technical_solvency:
        if not capacidad.referencias:
            items.append(
                ChecklistItem(
                    familia="technical_solvency",
                    requisito=requisito.description,
                    veredicto="desconocido",
                    motivo="La organización no ha declarado referencias de contratos.",
                    evidencia=list(requisito.evidence),
                )
            )
            continue

        umbral = _importe_en_texto(requisito.description)
        if umbral is not None:
            if not con_importe:
                items.append(
                    ChecklistItem(
                        familia="technical_solvency",
                        requisito=requisito.description,
                        veredicto="desconocido",
                        motivo=(
                            "El requisito exige un importe mínimo y ninguna referencia "
                            "declarada lleva importe."
                        ),
                        evidencia=list(requisito.evidence),
                    )
                )
                continue
            mejor = max(con_importe, key=lambda r: r.importe_eur or 0.0)
            importe_mejor = mejor.importe_eur or 0.0
            dato = f"{mejor.organo} ({mejor.anio}), {_eur(importe_mejor)}"
            if importe_mejor >= umbral:
                items.append(
                    _con_evidencia(
                        "technical_solvency",
                        requisito.description,
                        evidencia=list(requisito.evidence),
                        motivo=(
                            f"La mejor referencia declarada —{dato}— alcanza el umbral "
                            f"de {_eur(umbral)}."
                        ),
                        dato=dato,
                    )
                )
            else:
                items.append(
                    ChecklistItem(
                        familia="technical_solvency",
                        requisito=requisito.description,
                        veredicto="no_cumple",
                        motivo=(
                            f"La mejor referencia declarada —{dato}— no llega al umbral "
                            f"de {_eur(umbral)}."
                        ),
                        evidencia=list(requisito.evidence),
                        dato_organizacion=dato,
                    )
                )
            continue

        encaje = _referencia_por_tecnologia(requisito, capacidad.referencias)
        if encaje is None:
            items.append(
                ChecklistItem(
                    familia="technical_solvency",
                    requisito=requisito.description,
                    veredicto="desconocido",
                    motivo=(
                        "El requisito no cifra un importe ni nombra una tecnología de "
                        "las referencias declaradas: hay que contrastarlo a mano."
                    ),
                    evidencia=list(requisito.evidence),
                )
            )
            continue
        dato = f"{encaje.organo} ({encaje.anio}), {encaje.tecnologia}"
        items.append(
            _con_evidencia(
                "technical_solvency",
                requisito.description,
                evidencia=list(requisito.evidence),
                motivo=f"La organización declara una referencia de {encaje.tecnologia}: {dato}.",
                dato=dato,
            )
        )
    return items


def _perfil_que_encaja(
    requisito: TeamRequirement,
    perfiles: list[OrganizationTeamProfile],
) -> OrganizationTeamProfile | None:
    """El perfil de plantilla que responde al requisito, si alguno.

    Se busca en ``role`` si el extractor lo aisló y, si no, en la descripción:
    muchos pliegos no separan el rol del párrafo que lo exige.
    """
    texto = requisito.role or requisito.description
    for perfil in perfiles:
        if _contiene(texto, perfil.rol) or _contiene(perfil.rol, texto):
            return perfil
    return None


def _evaluar_equipo(
    facts: TenderFactSheet,
    capacidad: OrganizationCapabilities,
) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    for requisito in facts.team_requirements:
        etiqueta = requisito.role or requisito.description
        if not capacidad.perfiles_equipo:
            items.append(
                ChecklistItem(
                    familia="team_requirements",
                    requisito=etiqueta,
                    veredicto="desconocido",
                    motivo="La organización no ha declarado perfiles de equipo.",
                    evidencia=list(requisito.evidence),
                )
            )
            continue
        encaje = _perfil_que_encaja(requisito, capacidad.perfiles_equipo)
        if encaje is None:
            # Sin `role`, lo único que hay es texto libre: no casarlo dice más
            # de la extracción que de la plantilla.
            veredicto: ChecklistVeredicto = "no_cumple" if requisito.role else "desconocido"
            motivo = (
                f"Ningún perfil declarado corresponde a «{etiqueta}»."
                if requisito.role
                else (
                    "El pliego no identifica el perfil exigido, así que no se puede "
                    "casar con la plantilla declarada."
                )
            )
            items.append(
                ChecklistItem(
                    familia="team_requirements",
                    requisito=etiqueta,
                    veredicto=veredicto,
                    motivo=motivo,
                    evidencia=list(requisito.evidence),
                )
            )
            continue
        dato = f"{encaje.rol}: {encaje.cantidad} persona(s), {encaje.anios:g} años"
        if requisito.minimum_years is not None and encaje.anios < requisito.minimum_years:
            items.append(
                ChecklistItem(
                    familia="team_requirements",
                    requisito=etiqueta,
                    veredicto="no_cumple",
                    motivo=(
                        f"El pliego exige {requisito.minimum_years:g} años y la plantilla "
                        f"declara {encaje.anios:g}."
                    ),
                    evidencia=list(requisito.evidence),
                    dato_organizacion=dato,
                )
            )
            continue
        if requisito.quantity is not None and encaje.cantidad < requisito.quantity:
            items.append(
                ChecklistItem(
                    familia="team_requirements",
                    requisito=etiqueta,
                    veredicto="no_cumple",
                    motivo=(
                        f"El pliego exige {requisito.quantity} persona(s) y la plantilla "
                        f"declara {encaje.cantidad}."
                    ),
                    evidencia=list(requisito.evidence),
                    dato_organizacion=dato,
                )
            )
            continue
        items.append(
            _con_evidencia(
                "team_requirements",
                etiqueta,
                evidencia=list(requisito.evidence),
                motivo=f"La plantilla declarada cubre el perfil — {dato}.",
                dato=dato,
            )
        )
    return items


# ── Composición ────────────────────────────────────────────────────────────


def _veredicto_familia(items: list[ChecklistItem]) -> ChecklistVeredicto:
    """El peor de los ítems. Una familia sin ítems es ``desconocido``."""
    if not items:
        return "desconocido"
    if any(item.veredicto == "no_cumple" for item in items):
        return "no_cumple"
    if any(item.veredicto == "desconocido" for item in items):
        return "desconocido"
    return "cumple"


def _sin_hechos(familia: ChecklistFamilia) -> ChecklistItem:
    return ChecklistItem(
        familia=familia,
        requisito=_ETIQUETAS[familia],
        veredicto="desconocido",
        motivo=(f"La ficha del pliego no extrajo ningún requisito de «{_ETIQUETAS[familia]}»."),
    )


def evaluate(
    *,
    licitacion_id: str,
    organization_id: int,
    record: TenderFactSheetRecord | None,
    capabilities: OrganizationCapabilities,
    hoy: date,
) -> GoNoGoChecklist:
    """Contrasta una ficha contra un perfil. Función pura: ni lee ni escribe BD.

    Que sea pura es lo que permite que el golden la ejercite con fichas y
    capacidades sintéticas, sin Postgres de por medio.
    """
    facts = record.facts if record is not None else None
    if facts is None:
        facts = TenderFactSheet()

    por_familia: dict[ChecklistFamilia, list[ChecklistItem]] = {
        "certifications": _evaluar_certificaciones(facts, capabilities, hoy),
        "economic_solvency": _evaluar_solvencia_economica(facts, capabilities),
        "technical_solvency": _evaluar_solvencia_tecnica(facts, capabilities),
        "team_requirements": _evaluar_equipo(facts, capabilities),
    }

    familias: list[ChecklistFamiliaResultado] = []
    for familia in _FAMILIAS:
        items = por_familia[familia] or [_sin_hechos(familia)]
        familias.append(
            ChecklistFamiliaResultado(
                familia=familia,
                etiqueta=_ETIQUETAS[familia],
                veredicto=_veredicto_familia(por_familia[familia]),
                items=items,
            )
        )

    todos = [item for resultado in familias for item in resultado.items]
    return GoNoGoChecklist(
        licitacion_id=licitacion_id,
        organization_id=organization_id,
        ficha_estado=record.status if record is not None else None,
        extraction_version=record.extraction_version if record is not None else None,
        ficha_actualizada=record.updated_at if record is not None else None,
        familias=familias,
        total_requisitos=len(todos),
        cumple=sum(1 for item in todos if item.veredicto == "cumple"),
        no_cumple=sum(1 for item in todos if item.veredicto == "no_cumple"),
        desconocido=sum(1 for item in todos if item.veredicto == "desconocido"),
    )


def _clave_de_sellado(checklist: GoNoGoChecklist) -> str:
    """Una evaluación por versión de ficha, no una por visita a la pestaña.

    La versión sola no basta: reextraer el mismo pliego con el mismo extractor
    produce otra ficha (documentos nuevos, OCR) bajo la misma
    ``extraction_version``, y ese sí es un checklist distinto que merece su
    evento. De ahí que la fecha de la ficha entre en la clave.
    """
    version = checklist.extraction_version or "sin_version"
    fecha = checklist.ficha_actualizada or "sin_fecha"
    return f"checklist:{version}:{fecha}"


def build_checklist(
    user_id: int,
    pursuit_id: int,
    *,
    organization_id: int | None = None,
    hoy: date | None = None,
) -> GoNoGoChecklist:
    """Checklist de una oportunidad, sellado una vez por versión de ficha."""
    resolved_id, _ = resolve_organization(user_id, organization_id)
    row = _pursuit_repo.get(resolved_id, pursuit_id)
    if row is None:
        raise ChecklistNotFoundError("Oportunidad no encontrada.")

    licitacion_id = str(row["licitacion_id"])
    raw = _fact_sheets_repo.get(licitacion_id)
    record = TenderFactSheetRecord.model_validate(raw) if raw else None
    capabilities = OrganizationCapabilities.model_validate(_capabilities_repo.get(resolved_id))
    checklist = evaluate(
        licitacion_id=licitacion_id,
        organization_id=resolved_id,
        record=record,
        capabilities=capabilities,
        hoy=hoy or date.today(),
    )

    # Sin ficha no hay nada que sellar: el ledger contaría «se evaluó» de algo
    # que no se pudo evaluar.
    if record is not None:
        payload: dict[str, Any] = {
            "licitacion_id": licitacion_id,
            "extraction_version": checklist.extraction_version,
            "ficha_actualizada": checklist.ficha_actualizada,
            "cumple": checklist.cumple,
            "no_cumple": checklist.no_cumple,
            "desconocido": checklist.desconocido,
            "familias": {
                resultado.familia: resultado.veredicto for resultado in checklist.familias
            },
        }
        try:
            seal_checklist_evaluated(
                pursuit_id=pursuit_id,
                organization_id=resolved_id,
                actor_user_id=user_id,
                payload=payload,
                idempotency_key=_clave_de_sellado(checklist),
            )
        except Exception as exc:  # el ledger no puede tumbar la lectura
            log.warning("checklist_seal_failed", pursuit_id=pursuit_id, error=str(exc)[:200])
    return checklist
