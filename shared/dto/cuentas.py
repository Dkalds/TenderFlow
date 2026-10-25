"""Cuentas objetivo, etiquetas y enlace de calendario (F1.5, F1.6)."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.dto.primitivas import SafeStr

# ── Cuentas objetivo y etiquetas (F1.5, F1.6) ───────────────────────────────


class CuentaOrgano(BaseModel):
    """Un órgano de contratación de una cuenta (v145)."""

    model_config = ConfigDict(extra="forbid")

    #: Id de la fila en ``cuenta_organos``: es lo que se borra para quitarlo.
    id: int = Field(ge=1)
    #: Tal como lo publica la fuente.
    organo_nombre: str = Field(min_length=1, max_length=500)
    #: Plegado: la clave con la que casa contra las licitaciones.
    organo_norm: str
    #: El del maestro de órganos (C1.2). Vacío mientras el maestro no cubra el
    #: corpus: en 2026-09 tenía 248 órganos y ninguno de los seis del
    #: Ayuntamiento de Madrid.
    organo_id: int | None = None


class CuentaObjetivo(BaseModel):
    """Una cuenta de la organización: un cliente y sus órganos de contratación.

    Hasta v145 una cuenta **era** un órgano. Desde entonces tiene nombre propio
    y uno o varios órganos (``organos``), porque un cliente no publica con un
    solo nombre: el Ayuntamiento de Madrid contrata a través de seis órganos y
    ninguno se llama así.

    ``organo_nombre``, ``organo_norm`` y ``organo_id`` son el contrato anterior
    y se conservan por compatibilidad: dicen el **primer** órgano de la cuenta,
    que en una cuenta de un solo órgano es exactamente lo que decían. Para una
    cuenta de varios, usa ``organos``.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    #: Cómo llama el equipo a la cuenta. Por defecto, el nombre de su primer
    #: órgano; editable.
    nombre: str = Field(min_length=1, max_length=500)
    organo_nombre: str = Field(min_length=1, max_length=500)
    organo_norm: str
    organo_id: int | None = None
    organos: list[CuentaOrgano] = Field(default_factory=list)
    created_by_user_id: int | None = None
    created_at: str
    nota: str | None = Field(default=None, max_length=2000)


class AmbitoCifra(BaseModel):
    """Qué cuenta una cifra (ADR-014): sobre qué universo y en qué ventana.

    Viaja con el dato y no escrito en el cliente: si la consulta cambia de
    universo, la explicación cambia con ella.
    """

    model_config = ConfigDict(extra="forbid")

    universo: str
    ventana: str


class CuentaResumen(BaseModel):
    """Lo que pasa hoy en una cuenta, en cuatro números."""

    model_config = ConfigDict(extra="forbid")

    cuenta_id: int = Field(ge=1)
    abiertas: int = Field(ge=0)
    #: ``primera_extraccion`` más reciente de sus órganos; ``None`` si nunca
    #: se vio ninguno en el universo.
    ultima_publicacion: str | None = None
    vencen: int = Field(ge=0)
    oportunidades_activas: int = Field(ge=0)


class CuentasResumen(BaseModel):
    """El resumen de todas las cuentas de la organización, con su ámbito."""

    model_config = ConfigDict(extra="forbid")

    #: Una fila por cuenta, también las que están a cero.
    filas: list[CuentaResumen] = Field(default_factory=list)
    ambito_abiertas: AmbitoCifra
    ambito_ultima_publicacion: AmbitoCifra
    ambito_vencen: AmbitoCifra
    ambito_oportunidades: AmbitoCifra


class PublicacionCuenta(BaseModel):
    """Un expediente de un órgano de la cuenta."""

    model_config = ConfigDict(extra="forbid")

    id_externo: str
    titulo: str | None = None
    organo: str | None = None
    #: Alias de la base sin IVA (ADR-032 §A); ``importe_tipo`` dice si esta
    #: fila la trae o si es un histórico de base desconocida.
    importe: float | None = None
    importe_tipo: str | None = None
    fecha_publicacion: str | None = None
    fecha_limite: str | None = None
    primera_extraccion: str | None = None
    url: str | None = None
    #: Plazo de ofertas abierto hoy.
    abierta: bool = False


class VencimientoCuenta(BaseModel):
    """Un contrato de la cuenta que vence, con quien lo tiene."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    titulo: str | None = None
    organo: str | None = None
    empresa_id: int | None = None
    #: El adjudicatario actual: a quien hay que desplazar en la relicitación.
    empresa: str | None = None
    importe_adjudicado: float | None = None
    fecha_fin: str
    #: ``real`` o de qué rama se estimó (``fecha_fin_origen_sql``): el ~94 %
    #: de las fechas de fin se calcula, y la UI lo rotula.
    fecha_fin_origen: str


class OportunidadCuenta(BaseModel):
    """Una oportunidad del equipo sobre un expediente de la cuenta."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    licitacion_id: str
    lote_numero: str | None = None
    titulo: str | None = None
    status: str
    activa: bool
    next_action: str | None = None
    next_action_due: str | None = None
    responsable: str | None = None


class BloquePublicacionesCuenta(BaseModel):
    """Publicaciones recientes de la cuenta."""

    model_config = ConfigDict(extra="forbid")

    ambito: AmbitoCifra
    #: Cuántas hay en la ventana; ``items`` trae las primeras.
    total: int = Field(ge=0)
    items: list[PublicacionCuenta] = Field(default_factory=list)


class BloqueVencimientosCuenta(BaseModel):
    """Contratos de la cuenta que vencen en la ventana."""

    model_config = ConfigDict(extra="forbid")

    ambito: AmbitoCifra
    #: Contratos distintos. ``items`` son pares contrato-adjudicatario: una
    #: UTE son varias empresas a las que desplazar.
    total: int = Field(ge=0)
    items: list[VencimientoCuenta] = Field(default_factory=list)


class BloqueOportunidadesCuenta(BaseModel):
    """Lo que el equipo tiene con la cuenta."""

    model_config = ConfigDict(extra="forbid")

    ambito: AmbitoCifra
    activas: int = Field(ge=0)
    items: list[OportunidadCuenta] = Field(default_factory=list)


class FichaCuenta(BaseModel):
    """La ficha de una cuenta: el cliente, sus órganos y qué pasa con él."""

    model_config = ConfigDict(extra="forbid")

    cuenta: CuentaObjetivo
    publicaciones: BloquePublicacionesCuenta
    vencimientos: BloqueVencimientosCuenta
    oportunidades: BloqueOportunidadesCuenta


class OrganoCandidato(BaseModel):
    """Un órgano que el buscador del alta propone, y si ya es de una cuenta."""

    model_config = ConfigDict(extra="forbid")

    organo_nombre: str
    organo_norm: str
    #: Expedientes en el corpus: lo que distingue dos grafías parecidas.
    expedientes: int = Field(ge=0)
    cuenta_id: int | None = None
    cuenta_nombre: str | None = None


#: Qué se puede etiquetar (D38). Cerrado: cada tipo tiene su tabla y su forma
#: de clave, y añadir uno exige decidir cómo se limpia al borrar el objeto.
ObjetoEtiquetable = Literal["favorito", "oportunidad", "cuenta"]

#: Color hex de una etiqueta. Se valida la forma —no la legibilidad— porque el
#: contraste lo garantiza el componente, que pinta el texto en blanco o negro
#: según la luminancia del fondo.
_COLOR_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class Etiqueta(BaseModel):
    """Una etiqueta de la organización."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    nombre: str = Field(min_length=1, max_length=40)
    nombre_norm: str
    color: str
    created_by_user_id: int | None = None
    created_at: str

    @field_validator("color")
    @classmethod
    def _color_hex(cls, value: str) -> str:
        if not _COLOR_HEX_RE.match(value):
            raise ValueError("El color debe ser hexadecimal de seis dígitos (#rrggbb).")
        return value.lower()


class EtiquetaAplicada(BaseModel):
    """La etiqueta tal como se pinta junto al objeto: sólo lo que se ve."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    nombre: str
    color: str


class EtiquetaCreate(BaseModel):
    """Alta de etiqueta."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nombre: SafeStr = Field(min_length=1, max_length=40)
    color: str = Field(default="#64748b")

    @field_validator("color")
    @classmethod
    def _color_hex(cls, value: str) -> str:
        if not _COLOR_HEX_RE.match(value):
            raise ValueError("El color debe ser hexadecimal de seis dígitos (#rrggbb).")
        return value.lower()


class EtiquetaAplicacion(BaseModel):
    """Aplicar o quitar una etiqueta de un objeto."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    etiqueta_id: int = Field(ge=1)
    objeto_tipo: ObjetoEtiquetable
    objeto_id: SafeStr = Field(min_length=1, max_length=120)


#: Órganos que caben en una cuenta de una sola vez. Un cliente grande tiene
#: decenas de órganos, pero una selección de más de cincuenta en un formulario
#: es un error de uso, no una cuenta.
MAX_ORGANOS_POR_ALTA = 50

OrganoDeCuenta = Annotated[SafeStr, Field(min_length=1, max_length=500)]


class CuentaObjetivoCreate(BaseModel):
    """Alta de una cuenta: un órgano (``organo``) o un cliente con varios (``organos``).

    ``organo`` es el contrato de siempre —seguir un órgano, un clic— y conserva
    su semántica: si el órgano ya es de una cuenta, devuelve esa. ``organos``
    crea una cuenta nueva con todos, todo o nada. Va uno de los dos, no ambos.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    organo: OrganoDeCuenta | None = None
    organos: list[OrganoDeCuenta] | None = Field(
        default=None, min_length=1, max_length=MAX_ORGANOS_POR_ALTA
    )
    #: Cómo se llamará la cuenta. Por defecto, el primer órgano.
    nombre: SafeStr | None = Field(default=None, min_length=1, max_length=500)
    nota: SafeStr | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _un_camino(self) -> CuentaObjetivoCreate:
        if (self.organo is None) == (self.organos is None):
            raise ValueError("Indica un órgano (`organo`) o una lista de órganos (`organos`).")
        return self


class CuentaObjetivoUpdate(BaseModel):
    """Renombrar una cuenta o cambiar su nota.

    Un campo ausente no se toca; ``nota: null`` la borra. Es la diferencia que
    ``POST /cuentas`` no puede expresar: allí una nota vacía significa «no
    cambies la que hay».
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nombre: SafeStr | None = Field(default=None, min_length=1, max_length=500)
    nota: SafeStr | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _algo_que_cambiar(self) -> CuentaObjetivoUpdate:
        if not self.model_fields_set:
            raise ValueError("Indica `nombre` o `nota`.")
        if "nombre" in self.model_fields_set and self.nombre is None:
            raise ValueError("Una cuenta no puede quedarse sin nombre.")
        return self


class CuentaOrganosAdd(BaseModel):
    """Añadir órganos a una cuenta que ya existe."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    organos: list[OrganoDeCuenta] = Field(min_length=1, max_length=MAX_ORGANOS_POR_ALTA)


class CalendarioEnlace(BaseModel):
    """Enlace de suscripción al calendario ICS del usuario."""

    model_config = ConfigDict(extra="forbid")

    #: Ruta relativa al origen del sitio; el cliente antepone su origen. Un
    #: cliente de calendario externo la consume tal cual.
    path: str
    #: Cuántos eventos devolvería hoy, para que la UI no ofrezca un calendario
    #: vacío sin decirlo.
    eventos: int = Field(ge=0)
