"""Capacidad de la organización: NIF, documentación acreditativa y solvencia."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.dto.primitivas import PgDateTime, SafeStr

# ── ANCLA S2 — capacidad de la organización (NIF, solvencia, go/no-go) ─────

#: Ámbito de una certificación: la acredita la empresa o una persona del
#: equipo. Es el mismo vocabulario que ``CertificationRequirement.scope`` de
#: ``shared/tender_facts.py`` menos ``other``, que en el pliego significa «no
#: se sabe» y en el perfil de la organización no tendría sentido declarar.
OrganizationCapabilityScope = Literal["company", "team"]

#: Familias del perfil que el checklist puede contrastar. Viaja en
#: ``OrganizationCapabilitiesOut.campos_incompletos`` para que la UI señale qué
#: falta rellenar antes de que el go/no-go conteste «desconocido».
OrganizationCapabilityField = Literal[
    "certificaciones",
    "facturacion",
    "referencias",
    "perfiles_equipo",
]


class OrganizationNif(BaseModel):
    """Un NIF/CIF con el que la organización se presenta a licitación.

    Son varios y no uno: un grupo concursa con la matriz, con filiales y en
    UTE, y el cierre por NIF tiene que reconocer a todas. ``principal`` marca
    la razón social con la que se presenta por defecto; el resto son igual de
    válidas para decidir si una adjudicación es suya.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    #: Se guarda ya normalizado (``services.normalization.normalize_nif``):
    #: sin espacios, guiones ni puntos y en mayúsculas. Comparar «B-12345678»
    #: con «B12345678» en SQL exigiría normalizar la columna en cada consulta.
    nif: SafeStr = Field(min_length=4, max_length=32)
    razon_social: SafeStr | None = Field(default=None, max_length=300)
    principal: bool = False


class OrganizationNifsIn(BaseModel):
    """Cuerpo del PUT: el conjunto completo de NIFs, no un alta suelta.

    Reemplazar entero evita el endpoint de borrado por id y hace que la
    pantalla mande siempre lo que el usuario ve, que es lo que espera.
    """

    model_config = ConfigDict(extra="forbid")

    nifs: list[OrganizationNif] = Field(default_factory=list, max_length=25)


class OrganizationNifOut(OrganizationNif):
    """Un NIF ya persistido, resuelto contra el maestro de empresas."""

    id: int = Field(ge=1)
    #: ``empresas.empresa_id`` cuando el maestro conoce ese NIF. Es lo que
    #: permite excluir a la propia organización de «contra quién»: sin esta
    #: resolución habría que comparar nombres, y los nombres no son claves.
    empresa_id: int | None = None
    created_at: PgDateTime


class OrganizationNifsOut(BaseModel):
    """Identidad fiscal completa de una organización."""

    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(ge=1)
    nifs: list[OrganizationNifOut] = Field(default_factory=list)


#: Tipo de documento acreditativo (v147). ``certificacion_tecnica`` es lo que
#: el checklist contrasta con el pliego (ISO 9001, ISO/IEC 27001, ENS, partner
#: de fabricante, títulos del equipo); el resto es la **documentación
#: administrativa** que una empresa tiene que tener al día para presentarse:
#: estar al corriente con la AEAT y con la Seguridad Social, la inscripción en
#: el ROLECE y la clasificación empresarial. Espejo del ``CHECK`` de v147.
OrganizationDocumentType = Literal[
    "certificacion_tecnica",
    "corriente_aeat",
    "corriente_seguridad_social",
    "rolece",
    "clasificacion_empresarial",
]

#: Las dos familias de documento: lo que acredita capacidad técnica y lo que
#: acredita que la empresa está en regla.
OrganizationDocumentCategory = Literal["tecnica", "administrativa"]

#: Estado de vigencia de un documento en el perfil de capacidad.
#:
#: ``caduca_pronto`` es «dentro de la ventana del primer aviso» (60 días),
#: ``sin_caducidad`` es que no se declaró fecha —no que valga para siempre—.
EstadoVigencia = Literal["vigente", "caduca_pronto", "caducado", "sin_caducidad"]


class OrganizationCertification(BaseModel):
    """Documento acreditativo de la organización: certificación o papeleo.

    El nombre histórico se conserva —es el esquema que ya consume la consola—
    aunque desde v147 la fila también puede ser documentación administrativa
    (``tipo``). Lo guardado antes no trae tipo y vale como certificación
    técnica, que es lo único que la pantalla dejaba declarar.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nombre: SafeStr = Field(min_length=1, max_length=300)
    tipo: OrganizationDocumentType = "certificacion_tecnica"
    ambito: OrganizationCapabilityScope = "company"
    #: ``None`` significa «sin caducidad declarada», no «vigente para
    #: siempre»: el checklist la da por vigente porque no tiene motivo para
    #: decir lo contrario, y lo dice en el motivo del veredicto.
    vigente_hasta: date | None = None

    @model_validator(mode="after")
    def _administrativa_es_de_empresa(self) -> OrganizationCertification:
        """La AEAT, la Seguridad Social, el ROLECE y la clasificación certifican
        a la empresa. Documentación administrativa «del equipo» no existe, y
        guardarlo así solo produciría un perfil que no dice la verdad."""
        if self.tipo != "certificacion_tecnica" and self.ambito != "company":
            raise ValueError(
                "La documentación administrativa la acredita la empresa, no una persona."
            )
        return self


class VigenciaDocumento(BaseModel):
    """Estado de vigencia de un documento del perfil, calculado en el servidor.

    Lo calcula ``services/documentacion_caducidad.py`` con el mismo criterio
    que los avisos de caducidad, para que la pestaña y el aviso no puedan
    discrepar sobre si un certificado está a punto de caducar.
    """

    model_config = ConfigDict(extra="forbid")

    nombre: str
    tipo: OrganizationDocumentType
    categoria: OrganizationDocumentCategory
    vigente_hasta: date | None = None
    estado: EstadoVigencia
    #: Días hasta ``vigente_hasta`` (negativo si ya caducó; ``0`` es su último
    #: día de vigencia). ``None`` sin caducidad declarada.
    dias_restantes: int | None = None


class OrganizationFacturacion(BaseModel):
    """Facturación de un ejercicio cerrado."""

    model_config = ConfigDict(extra="forbid")

    ejercicio: int = Field(ge=1990, le=2100)
    importe_eur: float = Field(ge=0)


class OrganizationReferencia(BaseModel):
    """Contrato ejecutado que sirve de referencia de solvencia técnica."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    organo: SafeStr = Field(min_length=1, max_length=300)
    importe_eur: float | None = Field(default=None, ge=0)
    anio: int = Field(ge=1990, le=2100)
    #: Familia del diccionario (``SAP``, ``MICROSOFT``…) o el nombre tal cual
    #: si la organización trabaja con algo que el diccionario no tiene.
    tecnologia: SafeStr | None = Field(default=None, max_length=100)
    #: ``licitaciones.id_externo`` cuando la referencia salió de la propia
    #: plataforma. Que sea opcional es deliberado: el histórico de una
    #: organización empieza mucho antes de que use TenderFlow.
    expediente_id: SafeStr | None = Field(default=None, max_length=200)


class OrganizationTeamProfile(BaseModel):
    """Perfil disponible en plantilla, con experiencia y cuántas personas."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    rol: SafeStr = Field(min_length=1, max_length=200)
    anios: float = Field(ge=0, le=60)
    cantidad: int = Field(ge=1, le=9999)


class OrganizationCapabilities(BaseModel):
    """Perfil de capacidad de la organización: con qué puede acreditarse.

    Es dato **corporativo**, no personal: pertenece a la organización y no a
    quien lo teclea, así que ni se exporta ni se borra con la cuenta de un
    usuario (RGPD Art. 17/20 cubren datos personales).
    """

    model_config = ConfigDict(extra="forbid")

    certificaciones: list[OrganizationCertification] = Field(default_factory=list, max_length=50)
    #: Los tres últimos ejercicios son lo que piden los pliegos españoles para
    #: la solvencia económica; guardar más no aporta y guardar menos obliga a
    #: pedirlo otra vez.
    facturacion: list[OrganizationFacturacion] = Field(default_factory=list, max_length=3)
    referencias: list[OrganizationReferencia] = Field(default_factory=list, max_length=100)
    perfiles_equipo: list[OrganizationTeamProfile] = Field(default_factory=list, max_length=50)


class OrganizationCapabilitiesOut(OrganizationCapabilities):
    """Perfil leído, con qué falta por rellenar."""

    organization_id: int = Field(ge=1)
    updated_at: PgDateTime | None = None
    #: Familias vacías. La UI las marca para que se entienda por qué el
    #: checklist de una oportunidad contesta «desconocido» en esa familia.
    campos_incompletos: list[OrganizationCapabilityField] = Field(default_factory=list)
    #: Vigencia de cada documento declarado, ordenada por la próxima
    #: caducidad (lo caducado primero, lo que no declara fecha al final).
    vigencias: list[VigenciaDocumento] = Field(default_factory=list)
