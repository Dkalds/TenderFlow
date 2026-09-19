"""F6.4 — definir lo que recibe un miembro nuevo al aceptar la invitación.

``services.cuentas.aplicar_plantillas`` copia las plantillas de la organización
a quien acaba de entrar, pero nadie podía **definirlas**: la tabla
``plantillas_organizacion`` solo tenía la plantilla de tareas (F4.6) y
``aplicar_plantillas`` no la usa. Este módulo es la otra mitad: leer, crear y
borrar las plantillas de miembro (reglas de seguimiento y vistas guardadas).

Sin migración: ``plantillas_organizacion.tipo`` es texto libre y
``contenido_json`` guarda la definición entera, el mismo almacén que usa F4.6.
Los tipos que aquí se aceptan son exactamente los que ``aplicar_plantillas``
sabe copiar (``regla``, ``vista``); una plantilla de otro tipo en la misma tabla
—la de tareas— no aparece en esta lista ni se puede borrar desde aquí.

Qué se guarda de una regla
--------------------------
Los criterios, no la identidad: ``id``, ``organization_id`` y ``visibility``
se descartan al guardar. La copia es **del miembro** y nace privada
(``_copiar_para_miembro``); guardar la visibilidad en la plantilla haría creer
que se respeta.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from db.repositories.cartera import PlantillasRepository
from observability.logging import get_logger
from services.organizations import OrganizationPermissionError, alcance_resuelto
from services.watchlist_rules import WatchlistRule

log = get_logger(__name__)

__all__ = [
    "MAX_PLANTILLAS",
    "TIPOS_MIEMBRO",
    "PlantillaMiembro",
    "PlantillaMiembroIn",
    "PlantillaNoEncontradaError",
    "PlantillasLimiteError",
    "PlantillasMiembroOut",
    "borrar_plantilla_miembro",
    "crear_plantilla_miembro",
    "leer_plantillas_miembro",
]

TipoPlantillaMiembro = Literal["regla", "vista"]

#: Los tipos que ``aplicar_plantillas`` copia a un miembro.
TIPOS_MIEMBRO: frozenset[str] = frozenset({"regla", "vista"})

#: Tope por organización. Un miembro nuevo que recibe cincuenta reglas no
#: empieza con el método del equipo, empieza con ruido que tiene que borrar.
MAX_PLANTILLAS = 20

#: Mismo tope que ``POST /saved-filters`` para el JSON de una vista.
_MAX_FILTERS_JSON = 8_000

#: Campos de la regla que no son criterio y no viajan a la plantilla.
_CAMPOS_DE_IDENTIDAD = {"id", "organization_id", "visibility"}

_repo = PlantillasRepository()


class PlantillasLimiteError(ValueError):
    """La organización llegó a :data:`MAX_PLANTILLAS`."""


class PlantillaNoEncontradaError(LookupError):
    """La plantilla no existe, no es de esta organización o no es de miembro."""


class PlantillaMiembroIn(BaseModel):
    """Cuerpo del alta: una regla o una vista, según ``tipo``."""

    model_config = ConfigDict(extra="forbid")

    tipo: TipoPlantillaMiembro
    nombre: str = Field(min_length=1, max_length=120)
    #: Obligatoria con ``tipo='regla'``: los criterios de la regla.
    regla: WatchlistRule | None = None
    #: Obligatorio con ``tipo='vista'``: el mismo ``filters_json`` que guarda
    #: ``POST /saved-filters`` (un objeto JSON serializado).
    filters_json: str | None = Field(default=None, max_length=_MAX_FILTERS_JSON)

    @model_validator(mode="after")
    def _contenido_del_tipo(self) -> PlantillaMiembroIn:
        if not self.nombre.strip():
            raise ValueError("El nombre de la plantilla no puede estar vacío.")
        if self.tipo == "regla":
            if self.regla is None:
                raise ValueError("Una plantilla de regla necesita `regla`.")
            if self.filters_json is not None:
                raise ValueError("Una plantilla de regla no lleva `filters_json`.")
        else:
            if self.regla is not None:
                raise ValueError("Una plantilla de vista no lleva `regla`.")
            if not self.filters_json:
                raise ValueError("Una plantilla de vista necesita `filters_json`.")
            try:
                criterio = json.loads(self.filters_json)
            except (TypeError, ValueError) as exc:
                raise ValueError("`filters_json` no es JSON válido.") from exc
            if not isinstance(criterio, dict):
                raise ValueError("`filters_json` tiene que ser un objeto JSON.")
        return self


class PlantillaMiembro(BaseModel):
    """Una plantilla guardada, en la forma en que la edita la pantalla."""

    model_config = ConfigDict(extra="forbid")

    id: int
    tipo: TipoPlantillaMiembro
    nombre: str
    regla: WatchlistRule | None = None
    filters_json: str | None = None
    created_at: str | None = None


class PlantillasMiembroOut(BaseModel):
    """Las plantillas de miembro de la organización."""

    model_config = ConfigDict(extra="forbid")

    organization_id: int
    plantillas: list[PlantillaMiembro] = Field(default_factory=list)
    max_plantillas: int = MAX_PLANTILLAS
    #: Owner/admin. Los demás las ven en sólo lectura.
    puede_editar: bool = False


def _contenido(plantilla: PlantillaMiembroIn) -> dict[str, Any]:
    """Lo que se guarda en ``contenido_json``, en la forma que lee la copia."""
    if plantilla.tipo == "regla" and plantilla.regla is not None:
        criterios = plantilla.regla.model_dump(exclude=_CAMPOS_DE_IDENTIDAD, exclude_none=True)
        return {**criterios, "nombre": plantilla.regla.nombre or plantilla.nombre.strip()}
    return {
        "nombre": plantilla.nombre.strip(),
        "criterio": json.loads(plantilla.filters_json or "{}"),
    }


def _a_dto(fila: dict[str, Any]) -> PlantillaMiembro | None:
    """La fila como DTO, o ``None`` si no es de miembro o está corrupta."""
    tipo = str(fila.get("tipo") or "")
    if tipo not in TIPOS_MIEMBRO:
        return None
    contenido = fila.get("contenido") or {}
    try:
        if tipo == "regla":
            regla = WatchlistRule.model_validate(contenido)
            return PlantillaMiembro(
                id=int(fila["id"]),
                tipo="regla",
                nombre=str(fila.get("nombre") or ""),
                regla=regla,
                created_at=fila.get("created_at"),
            )
        return PlantillaMiembro(
            id=int(fila["id"]),
            tipo="vista",
            nombre=str(fila.get("nombre") or ""),
            filters_json=json.dumps(contenido.get("criterio") or {}, ensure_ascii=False),
            created_at=fila.get("created_at"),
        )
    except ValueError:
        # Una plantilla ilegible no tumba la lista: se omite y el log dice cuál.
        log.warning("plantilla_miembro_ilegible", plantilla_id=fila.get("id"), tipo=tipo)
        return None


def _de_miembro(organization_id: int) -> list[PlantillaMiembro]:
    filas = _repo.list_for_organization(organization_id)
    return [dto for fila in filas if (dto := _a_dto(fila)) is not None]


def leer_plantillas_miembro(user_id: int, organization_id: int | None) -> PlantillasMiembroOut:
    """Cualquier miembro las ve; ``puede_editar`` dice si además las cambia."""
    with alcance_resuelto(user_id, organization_id) as (resuelta, rol):
        return PlantillasMiembroOut(
            organization_id=resuelta,
            plantillas=_de_miembro(resuelta),
            puede_editar=rol in {"owner", "admin"},
        )


def _exigir_gestor(rol: str) -> None:
    if rol not in {"owner", "admin"}:
        raise OrganizationPermissionError(
            "Solo un owner o admin puede cambiar las plantillas de la organización."
        )


def crear_plantilla_miembro(
    user_id: int, organization_id: int | None, plantilla: PlantillaMiembroIn
) -> PlantillasMiembroOut:
    """Añade una plantilla. Solo owner y admin; hasta :data:`MAX_PLANTILLAS`.

    No se aplica a los miembros que ya estaban: la copia ocurre al activar la
    membresía, una sola vez. Repartir una regla nueva a todo el equipo sería
    otra función —y otra conversación sobre quién la pidió—.
    """
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, rol):
        _exigir_gestor(rol)
        if len(_de_miembro(resuelta)) >= MAX_PLANTILLAS:
            raise PlantillasLimiteError(
                f"La organización ya tiene {MAX_PLANTILLAS} plantillas de miembro, "
                "que es el máximo. Borra alguna antes de crear otra."
            )
        _repo.create(
            organization_id=resuelta,
            tipo=plantilla.tipo,
            nombre=plantilla.nombre,
            contenido=_contenido(plantilla),
            user_id=user_id,
        )
        log.info("plantilla_miembro_creada", organization_id=resuelta, tipo=plantilla.tipo)
        return PlantillasMiembroOut(
            organization_id=resuelta, plantillas=_de_miembro(resuelta), puede_editar=True
        )


def borrar_plantilla_miembro(
    user_id: int, organization_id: int | None, plantilla_id: int
) -> PlantillasMiembroOut:
    """Borra una plantilla de miembro. No toca las copias ya repartidas.

    Una plantilla de otro tipo (la de tareas de F4.6) responde como no
    encontrada: esta superficie no la gestiona, y borrarla desde aquí
    rompería el método del equipo sin que la pantalla lo enseñara.
    """
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, rol):
        _exigir_gestor(rol)
        if all(p.id != plantilla_id for p in _de_miembro(resuelta)):
            raise PlantillaNoEncontradaError("La plantilla no existe.")
        _repo.delete(resuelta, plantilla_id)
        return PlantillasMiembroOut(
            organization_id=resuelta, plantillas=_de_miembro(resuelta), puede_editar=True
        )
