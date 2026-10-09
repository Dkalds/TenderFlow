"""Carga del equipo: quién tiene qué abierto hoy, y qué de eso pide atención.

Es la pregunta de Dirección que el cuadro de resultados no responde: «¿el
equipo está trabajando lo que dijimos que íbamos a trabajar?». Los resultados
miran al pasado (qué se ganó); esto es la foto de hoy (qué hay encima de la
mesa de cada persona), y por eso vive en su propia vista y no en una tarjeta
más.

Cada cifra es un recuento de oportunidades **abiertas**, agregado aquí y no en
la pantalla (ADR-014). Lo que se cuenta como «pide atención» excluye las
presentadas: una oferta entregada espera un resultado, no trabajo de oferta, y
contarla en «sin próxima acción» acusaría a quien ya hizo su parte.

Mismo permiso que el cuadro (owner y admin), comprobado en el servicio con
:func:`services.direccion.direccion_resuelta`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuits import PursuitRepository
from services.direccion import direccion_resuelta
from services.pursuits import _parse_iso_date
from shared.dates import a_fecha

__all__ = [
    "CARGA_MAX_OPORTUNIDADES",
    "HORIZONTE_CARGA_DIAS",
    "CargaEquipo",
    "CargaResponsable",
    "carga_del_equipo",
    "construir_carga",
]

#: Horizonte de «plazo próximo». Catorce días, el mismo que el informe semanal
#: (``services.informes.DIAS_VENCIMIENTO``): preparar una oferta lleva más de
#: una semana.
HORIZONTE_CARGA_DIAS = 14

#: Techo de oportunidades abiertas que lee la carga. Si una organización lo
#: supera, la respuesta lo dice (``truncado``) en vez de enseñar cargas bajas.
CARGA_MAX_OPORTUNIDADES = 500


class CargaResponsable(BaseModel):
    """Lo que tiene abierto una persona, y lo que de eso pide atención."""

    model_config = ConfigDict(extra="forbid")

    #: `None` = oportunidades sin responsable asignado.
    user_id: int | None = None
    nombre: str | None = None
    #: Abiertas en cualquier etapa, presentadas incluidas.
    abiertas: int = Field(default=0, ge=0)
    #: Presentadas, esperando resultado: ya no piden trabajo de oferta.
    presentadas: int = Field(default=0, ge=0)
    #: Sin presentar y con el plazo de presentación dentro del horizonte.
    plazos_proximos: int = Field(default=0, ge=0)
    #: Sin presentar y con el plazo ya pasado: el tablero las arrastra.
    plazos_vencidos: int = Field(default=0, ge=0)
    #: Sin presentar y sin próxima acción: nadie ha dicho qué toca.
    sin_proxima_accion: int = Field(default=0, ge=0)
    #: Sin presentar y con la próxima acción ya vencida.
    acciones_vencidas: int = Field(default=0, ge=0)


class CargaEquipo(BaseModel):
    """Carga del equipo: quién tiene qué abierto hoy."""

    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(ge=1)
    hoy: date
    horizonte_dias: int = Field(ge=1)
    total_abiertas: int = Field(default=0, ge=0)
    #: Una fila por miembro activo —también los que no tienen nada: que
    #: alguien esté libre es parte de la respuesta— y una para «sin
    #: responsable» si hay oportunidades sin asignar.
    responsables: list[CargaResponsable] = Field(default_factory=list)
    #: `True` si había más de `CARGA_MAX_OPORTUNIDADES` abiertas y la carga se
    #: calculó sobre las primeras: las cifras son un mínimo, no el total.
    truncado: bool = False


def construir_carga(
    organization_id: int,
    filas: Sequence[Mapping[str, Any]],
    miembros: Sequence[Mapping[str, Any]],
    *,
    hoy: date,
    truncado: bool = False,
) -> CargaEquipo:
    """Agrega las oportunidades abiertas por responsable. Función pura."""
    limite = hoy + timedelta(days=HORIZONTE_CARGA_DIAS)
    cargas: dict[int | None, CargaResponsable] = {}
    for miembro in miembros:
        if str(miembro.get("status") or "active") != "active":
            continue
        user_id = int(miembro["user_id"])
        cargas[user_id] = CargaResponsable(
            user_id=user_id,
            nombre=str(miembro.get("display_name") or miembro.get("email") or "") or None,
        )

    for fila in filas:
        responsable = fila.get("responsible_user_id")
        clave = int(responsable) if responsable is not None else None
        carga = cargas.get(clave)
        if carga is None:
            # Un responsable que ya no es miembro activo sigue teniendo las
            # oportunidades a su nombre: se enseña, con el nombre que traiga.
            nombre = fila.get("responsible_name")
            carga = CargaResponsable(user_id=clave, nombre=str(nombre) if nombre else None)
            cargas[clave] = carga
        carga.abiertas += 1
        if fila.get("status") == "submitted":
            carga.presentadas += 1
            continue
        plazo = _parse_iso_date(fila.get("tender_deadline"))
        if plazo is not None and plazo < hoy:
            carga.plazos_vencidos += 1
        elif plazo is not None and plazo <= limite:
            carga.plazos_proximos += 1
        if not str(fila.get("next_action") or "").strip():
            carga.sin_proxima_accion += 1
        vence = a_fecha(fila.get("next_action_due"))
        if vence is not None and vence < hoy:
            carga.acciones_vencidas += 1

    responsables = sorted(
        cargas.values(),
        # Sin responsable al final; el resto por carga y, a igualdad, por nombre.
        key=lambda c: (c.user_id is None, -c.abiertas, (c.nombre or "").lower()),
    )
    return CargaEquipo(
        organization_id=organization_id,
        hoy=hoy,
        horizonte_dias=HORIZONTE_CARGA_DIAS,
        total_abiertas=len(filas),
        responsables=responsables,
        truncado=truncado,
    )


def carga_del_equipo(user_id: int, organization_id: int | None) -> CargaEquipo:
    """Quién tiene qué abierto. Mismo permiso que el cuadro: owner y admin.

    El ``with`` envuelve las dos lecturas: el ámbito de tenencia (ADR-034)
    tiene que seguir abierto donde están las consultas.
    """
    with direccion_resuelta(user_id, organization_id) as resuelta:
        filas, truncado = PursuitRepository().agenda_rows(resuelta, limit=CARGA_MAX_OPORTUNIDADES)
        miembros = OrganizationRepository().list_members(resuelta)
        return construir_carga(
            resuelta, filas, miembros, hoy=datetime.now(UTC).date(), truncado=truncado
        )
