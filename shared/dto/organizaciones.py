"""Organizaciones: miembros, configuración, informe programado, invitaciones y auditoría."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from shared.dto.primitivas import PgDateTime, SafeStr

# ── Organizaciones y pursuits (Fase 1 TenderFlow) ──────────────────────────

OrganizationRole = Literal["owner", "admin", "member", "viewer"]
OrganizationMembershipStatus = Literal["active", "invited", "suspended", "revoked"]


class OrganizationSummary(BaseModel):
    """Organización de trabajo visible para el usuario autenticado."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    is_personal: bool
    role: OrganizationRole
    created_at: PgDateTime


class OrganizationMembershipOut(BaseModel):
    """Membresía sin datos de autenticación ni credenciales."""

    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(ge=1)
    user_id: int = Field(ge=1)
    role: OrganizationRole
    status: OrganizationMembershipStatus
    created_at: PgDateTime
    updated_at: PgDateTime
    display_name: str | None = None
    email: str | None = None


class OrganizationCreate(BaseModel):
    """Alta de un espacio compartido."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    #: ``SafeStr`` y no ``str``: el nombre se inserta tal cual en Postgres y un
    #: byte NUL en el cuerpo salía por el handler genérico como 500. El
    #: middleware que rechaza el NUL solo mira la línea de petición.
    name: SafeStr = Field(min_length=1, max_length=200)


class OrganizationMembershipUpsert(BaseModel):
    """Alta o cambio de rol/estado de un miembro existente."""

    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(ge=1)
    role: OrganizationRole = "member"
    status: OrganizationMembershipStatus = "active"


class OrganizationMemberInvite(BaseModel):
    """Alta de un miembro por correo.

    Si el correo ya tiene cuenta activa, la persona entra al equipo en el acto
    (``OrganizationMembershipOut``). Si no la tiene, se crea una invitación
    pendiente y se le manda un enlace firmado (``OrganizationInvitationOut``):
    hasta 2026-09 este segundo caso respondía 404 y la única salida era pedirle
    que se registrara primero.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    role: Literal["admin", "member", "viewer"] = "member"


#: Probabilidad por defecto de cada etapa del embudo, en porcentaje (D34).
#:
#: **Son supuestos, no medidas**, y así se declaran en la respuesta: hasta que
#: F3.1 acumule cierres no hay histórico con el que calibrarlos. Owner y admin
#: los editan. Se eligen crecientes y sin llegar al 100 % porque una
#: oportunidad presentada sigue pudiendo perderse; poner `submitted` al 100 %
#: convertiría el valor ponderado en la suma del pipeline, que es el número
#: que este campo existe para dejar de publicar.
PROBABILIDADES_ETAPA_DEFAULT: dict[str, int] = {
    "identified": 10,
    "qualifying": 20,
    "go_no_go": 30,
    "preparing": 50,
    "submitted": 60,
}


class OrganizationSettings(BaseModel):
    """Configuración de producto de una organización (``organizations.settings_json``).

    ``tecnologias`` son las familias del diccionario (``SAP``, ``MICROSOFT``…)
    que vende la organización. Vacío significa «todas»: el Radar puntúa el
    universo entero, como hasta 2026-09. Con familias declaradas, el Radar
    acota su universo a ellas cuando el usuario no filtra por tecnología a
    mano, y la ingesta no cambia —el filtro es una vista sobre el corpus, no
    una pérdida de datos.

    **Ámbito de mercado (F6.1).** El resto de campos de ámbito —CPVs, CCAAs,
    rango de importe, tipos de órgano y procedimientos excluidos— vivían sólo
    en el perfil **personal** (``api/routes/me.py``), así que cada miembro
    tenía que reconfigurar a mano lo que la organización entera comparte, y
    quien no lo hacía veía el mercado sin acotar. Aquí son de la organización,
    y la precedencia es explícita: **perfil personal → organización → global**.
    En todos, la lista vacía significa «sin restricción», nunca «ninguno»: un
    ámbito que se interpretara al revés vaciaría el Radar en silencio el día
    que alguien guardara la configuración sin tocar un campo.

    No hay migración: ``organizations.settings_json`` es JSON y admite claves
    nuevas. La que D39 pre-autorizaba no hace falta.
    """

    model_config = ConfigDict(extra="forbid")

    tecnologias: list[str] = Field(default_factory=list, max_length=30)
    #: CPVs por **prefijo**, como en el filtro del listado (F1.1): `72` es
    #: «servicios de TI» entero.
    cpvs: list[str] = Field(default_factory=list, max_length=50)
    ccaas: list[str] = Field(default_factory=list, max_length=25)
    importe_min: float | None = Field(default=None, ge=0)
    importe_max: float | None = Field(default=None, ge=0)
    #: Tipos de órgano que interesan, contra `organos.tipo` del maestro (C1.2).
    #: El Radar solo excluye los órganos con un tipo **conocido y distinto**:
    #: el maestro todavía no rellena `tipo`, y exigirlo vaciaría el Radar.
    tipos_organo: list[str] = Field(default_factory=list, max_length=20)
    #: Procedimientos que la organización **no** quiere ver. Es una lista de
    #: exclusión y no de inclusión porque así es como se usa: casi nadie
    #: enumera los diez procedimientos que le valen, pero mucha gente quiere
    #: quitar los contratos menores del Radar.
    procedimientos_excluidos: list[str] = Field(default_factory=list, max_length=20)
    #: F4.1 — probabilidad por etapa para el valor ponderado del pipeline.
    #: Vacío = se usan los `PROBABILIDADES_ETAPA_DEFAULT`.
    probabilidades_etapa: dict[str, int] = Field(default_factory=dict)

    @field_validator("tecnologias")
    @classmethod
    def _normaliza_tecnologias(cls, value: list[str]) -> list[str]:
        vistas: list[str] = []
        for raw in value:
            code = str(raw).strip().upper()
            if code and code not in vistas:
                vistas.append(code)
        return vistas

    @field_validator("cpvs", "ccaas", "tipos_organo", "procedimientos_excluidos")
    @classmethod
    def _limpia_lista(cls, value: list[str]) -> list[str]:
        """Sin vacíos ni duplicados, conservando el orden en que se guardaron."""
        vistas: list[str] = []
        for raw in value:
            item = str(raw).strip()
            if item and item not in vistas:
                vistas.append(item)
        return vistas

    @field_validator("probabilidades_etapa")
    @classmethod
    def _valida_probabilidades(cls, value: dict[str, int]) -> dict[str, int]:
        """Sólo etapas conocidas y sólo porcentajes 0-100.

        Una etapa inventada se rechaza en vez de ignorarse: guardarla en
        silencio dejaría a un admin creyendo que configuró algo que no existe,
        y el valor ponderado seguiría usando el default sin decirlo.
        """
        limpio: dict[str, int] = {}
        for etapa, pct in value.items():
            if etapa not in PROBABILIDADES_ETAPA_DEFAULT:
                raise ValueError(
                    f"Etapa desconocida: {etapa}. "
                    f"Válidas: {', '.join(sorted(PROBABILIDADES_ETAPA_DEFAULT))}."
                )
            entero = int(pct)
            if not 0 <= entero <= 100:
                raise ValueError(f"La probabilidad de {etapa} debe estar entre 0 y 100.")
            limpio[etapa] = entero
        return limpio

    @model_validator(mode="after")
    def _rango_de_importe_coherente(self) -> OrganizationSettings:
        if (
            self.importe_min is not None
            and self.importe_max is not None
            and self.importe_max < self.importe_min
        ):
            raise ValueError("importe_max no puede ser menor que importe_min.")
        return self

    def probabilidad_de(self, etapa: str) -> int:
        """Probabilidad efectiva de una etapa: la configurada o el default.

        Una etapa terminal (`won`, `lost`, `withdrawn`) devuelve 0: ya no está
        en el pipeline, y contarla en el valor ponderado sería sumar dos veces
        lo ganado (que ya tiene su propio `awarded_amount_eur`).
        """
        if etapa not in PROBABILIDADES_ETAPA_DEFAULT:
            return 0
        return self.probabilidades_etapa.get(etapa, PROBABILIDADES_ETAPA_DEFAULT[etapa])


class ReportSchedule(BaseModel):
    """Cuándo y a quién sale el informe semanal de una organización (T6).

    `dia_semana` es 0 = lunes, como `datetime.weekday()` y como el `CHECK` de
    v132. No es el `DOW` de Postgres (0 = domingo): mezclar las dos
    numeraciones desplaza el informe seis días, y por eso se dice aquí además
    de en la migración.
    """

    model_config = ConfigDict(extra="forbid")

    activo: bool = False
    dia_semana: int = Field(default=0, ge=0, le=6)
    #: Hora **UTC**. La interfaz la traduce al enseñarla; el scheduler razona en
    #: UTC de punta a punta (ADR-033).
    hora_utc: int = Field(default=7, ge=0, le=23)
    #: `None` o vacío = «los owner y admin de la organización». Dejarlo vacío es
    #: lo que hace que dar de alta a un administrador nuevo no exija acordarse
    #: de editar esta lista.
    destinatarios: list[EmailStr] | None = Field(default=None, max_length=25)


class ReportScheduleOut(ReportSchedule):
    """La programación leída, con lo que hizo el último envío.

    `extra="ignore"`, a diferencia del DTO de entrada: el repositorio devuelve
    la fila entera —`id`, `created_at`, `updated_at`, que el job sí usa— y con
    el `forbid` heredado **las dos rutas respondían 500** en cuanto existía una
    fila. La entrada conserva el `forbid` porque se valida contra
    `ReportSchedule`, no contra esta subclase: un campo inventado en el `PUT`
    sigue siendo un 422.
    """

    model_config = ConfigDict(extra="ignore")

    organization_id: int = Field(ge=1)
    tipo: str = "pipeline_semanal"
    ultimo_envio_at: PgDateTime | None = None
    #: `enviado:2/3`, `vacio`, `sin_destinatarios`, `fallido`. Es lo que
    #: responde «¿por qué no me llegó el informe?» sin abrir los logs.
    ultimo_estado: str | None = None


class OrganizationSettingsOut(OrganizationSettings):
    """Configuración leída, con la organización a la que pertenece."""

    organization_id: int = Field(ge=1)
    #: Familias válidas del diccionario, para que el cliente pinte el selector
    #: sin copiarse la lista a mano (invariante 3 de ``web/AGENTS.md``).
    tecnologias_disponibles: list[str] = Field(default_factory=list)
    #: F4.1 — los defaults vigentes, para que el formulario pueda enseñar «10 %
    #: (por defecto)» en vez de un hueco, y para que el cliente no lleve su
    #: propia copia de los supuestos de D34.
    probabilidades_etapa_default: dict[str, int] = Field(
        default_factory=lambda: dict(PROBABILIDADES_ETAPA_DEFAULT)
    )


# ── ANCLA S1 — identidad y equipo (invitaciones, proveedores OAuth) ────────

#: Estado de una invitación tal y como lo ve quien administra el equipo.
#: ``expired`` no se persiste: es ``expires_at`` en el pasado leído en el
#: momento de mostrarlo. Un estado derivado que además se guardara obligaría a
#: un job que lo mantuviera al día, y a explicar qué hacer cuando discrepan.
OrganizationInvitationStatus = Literal["invited", "accepted", "revoked", "expired"]


class OrganizationInvitationOut(BaseModel):
    """Invitación a un correo que todavía no tiene cuenta en TenderFlow.

    Es la contraparte de :class:`OrganizationMembershipOut` para el intervalo
    en el que aún no hay persona a la que apuntar: ``organization_memberships``
    exige ``user_id``, así que hasta que alguien se registra o entra por OAuth
    con ese correo la intención vive en ``organization_invitations``.

    Nunca lleva el token: el valor bruto existe solo en el correo enviado.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    email: str
    role: Literal["admin", "member", "viewer"]
    status: OrganizationInvitationStatus
    invited_by_user_id: int | None = None
    created_at: PgDateTime
    expires_at: PgDateTime
    accepted_at: PgDateTime | None = None


class OrganizationInvitationAccept(BaseModel):
    """Canje del token recibido por correo, desde una sesión ya iniciada."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    token: str = Field(min_length=16, max_length=512)


class AuditEntryOut(BaseModel):
    """Una entrada del rastro de auditoría de la organización.

    Es lo que sirve ``GET /organizations/{id}/audit`` (Ola 1 · Audit log). El
    actor viaja como ``users.id`` y nunca como correo (ADR-030 §D); ``detail``
    es el payload tal como se persistió —JSON o texto— y no un objeto: cada
    familia de ``shared/audit_events.py`` guarda claves distintas y declarar
    una forma por familia sería un contrato que nadie consume tipado.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    #: ISO 8601 en UTC, tal como lo escribe ``db.audit``.
    ts: str
    #: Uno de ``shared.audit_events.EVENTOS`` (los anteriores al catálogo
    #: pueden llevar nombres fuera de él).
    event_type: str
    actor_user_id: int | None = None
    outcome: str
    resource: str | None = None
    detail: str = ""
