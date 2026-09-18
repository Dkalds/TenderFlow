"""F4.6 — plantilla de tareas por etapa.

Un equipo con método prepara todas las ofertas igual: revisión legal,
solvencia, precio, entrega. Sin plantilla, cada oportunidad que pasa a
``preparing`` empieza con la lista de tareas en blanco y alguien la reescribe
de memoria —y se deja la que no recuerda—.

Qué hace
--------
- La organización guarda **una** plantilla de hasta veinte tareas, cada una
  con un plazo relativo a la fecha límite del expediente («cinco días antes»).
  Owner y admin la editan; el resto la ve.
- Cuando una oportunidad pasa a ``preparing``, se crean sus tareas **una sola
  vez**. La idempotencia la da un evento en ``pursuit_events`` con clave de
  idempotencia fija: el índice único parcial de v61 impide el segundo, así que
  dos transiciones simultáneas —o un reintento— no duplican el trabajo.

Dónde vive
----------
En ``plantillas_organizacion`` con ``tipo='tareas'`` (v106): la columna es
texto libre y ``contenido_json`` guarda la definición entera, así que no hace
falta migración. ``services.cuentas.aplicar_plantillas`` (F6.4) ignora este
tipo: no se copia a un miembro, se instancia en una oportunidad.

Sin ``origen`` en la tarea
--------------------------
El plan mide la adopción con «``origen=plantilla`` en la creación de tareas».
No se añade columna a ``pursuit_tasks`` para eso: el evento del ledger ya dice
qué oportunidades recibieron la plantilla y cuántas tareas, y el log
estructurado lleva ``origen="plantilla"``. Una columna sólo haría falta si una
pantalla tuviera que distinguir las tareas de plantilla de las manuales, y
ninguna lo pide.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from db.repositories.cartera import PlantillasRepository
from db.repositories.pursuit_tasks import PursuitTasksRepository
from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from services.organizations import OrganizationPermissionError, alcance_resuelto
from shared.dates import a_fecha

log = get_logger(__name__)

__all__ = [
    "ETAPA",
    "EVENTO_PLANTILLA",
    "MAX_TAREAS",
    "PlantillaTareas",
    "PlantillaTareasOut",
    "TareaPlantilla",
    "guardar_plantilla",
    "instanciar_en_pursuit",
    "leer_plantilla",
    "vence_relativo",
]

#: Tope del plan: «hasta veinte tareas». Por encima, la plantilla deja de ser
#: un método y se convierte en una lista que nadie termina.
MAX_TAREAS = 20

#: Tipo en ``plantillas_organizacion``. Texto libre en v106.
TIPO = "tareas"

#: La etapa que dispara la plantilla. Una sola, la del plan: es cuando empieza
#: el trabajo que se reparte. Constante y no configurable hasta que alguien
#: pida otra etapa con un caso real.
ETAPA: Literal["preparing"] = "preparing"

#: Evento del ledger que marca «esta oportunidad ya recibió la plantilla».
EVENTO_PLANTILLA = "plantilla_tareas_aplicada"

_plantillas = PlantillasRepository()
_tareas = PursuitTasksRepository()
_pursuits = PursuitRepository()


class TareaPlantilla(BaseModel):
    """Una tarea de la plantilla: título y plazo relativo a la fecha límite."""

    model_config = ConfigDict(extra="forbid")

    titulo: str = Field(min_length=1, max_length=300)
    #: Días **antes** de la fecha límite. ``None``: la tarea nace sin plazo.
    dias_antes_limite: int | None = Field(default=None, ge=0, le=365)

    @field_validator("titulo")
    @classmethod
    def _sin_blancos(cls, valor: str) -> str:
        limpio = valor.strip()
        if not limpio:
            raise ValueError("El título de la tarea no puede estar vacío.")
        return limpio


class PlantillaTareas(BaseModel):
    """Cuerpo del PUT: la plantilla entera, que sustituye a la anterior."""

    model_config = ConfigDict(extra="forbid")

    tareas: list[TareaPlantilla] = Field(default_factory=list, max_length=MAX_TAREAS)


class PlantillaTareasOut(PlantillaTareas):
    """La plantilla leída, con lo que la pantalla necesita para editarla."""

    organization_id: int
    etapa: Literal["preparing"] = ETAPA
    max_tareas: int = MAX_TAREAS
    #: Si quien lee puede editar (owner/admin). La UI enseña la plantilla en
    #: sólo lectura a los demás en vez de un formulario que acaba en 403.
    puede_editar: bool = False


def _tareas_guardadas(organization_id: int) -> list[TareaPlantilla]:
    filas = _plantillas.list_for_organization(organization_id, TIPO)
    if not filas:
        return []
    contenido = filas[-1].get("contenido") or {}
    crudas = contenido.get("tareas") if isinstance(contenido, dict) else None
    tareas: list[TareaPlantilla] = []
    for cruda in crudas if isinstance(crudas, list) else []:
        try:
            tareas.append(TareaPlantilla.model_validate(cruda))
        except ValueError:
            # Una entrada corrupta no tumba la plantilla entera: se omite y el
            # log dice cuál. La siguiente edición la deja limpia.
            log.warning("plantilla_tareas_entrada_invalida", organization_id=organization_id)
    return tareas[:MAX_TAREAS]


def leer_plantilla(user_id: int, organization_id: int | None) -> PlantillaTareasOut:
    """Cualquier miembro la ve; ``puede_editar`` dice si además la cambia."""
    with alcance_resuelto(user_id, organization_id) as (resuelta, rol):
        return PlantillaTareasOut(
            organization_id=resuelta,
            tareas=_tareas_guardadas(resuelta),
            puede_editar=rol in {"owner", "admin"},
        )


def guardar_plantilla(
    user_id: int, organization_id: int | None, plantilla: PlantillaTareas
) -> PlantillaTareasOut:
    """Sustituye la plantilla. Solo owner y admin.

    No toca las oportunidades que ya la recibieron: sus tareas son trabajo del
    equipo en curso, y reescribirlas porque cambió el método sería borrar lo
    que alguien ya empezó.
    """
    with alcance_resuelto(user_id, organization_id) as (resuelta, rol):
        if rol not in {"owner", "admin"}:
            raise OrganizationPermissionError(
                "Solo un owner o admin puede cambiar la plantilla de tareas."
            )
        _plantillas.reemplazar(
            organization_id=resuelta,
            tipo=TIPO,
            nombre="Tareas al preparar la oferta",
            contenido={"etapa": ETAPA, "tareas": [t.model_dump() for t in plantilla.tareas]},
            user_id=user_id,
        )
        return PlantillaTareasOut(
            organization_id=resuelta,
            tareas=_tareas_guardadas(resuelta),
            puede_editar=True,
        )


def vence_relativo(fecha_limite: Any, dias_antes: int | None) -> str | None:
    """``YYYY-MM-DD`` de la tarea, o ``None`` si no hay con qué calcularlo.

    Sin fecha límite no se inventa un plazo: la tarea nace sin fecha y el
    equipo se la pone. Un plazo que ya pasó se conserva tal cual —la tarea
    llega vencida—, porque adelantarlo a hoy escondería que el método pedía
    empezar antes.
    """
    if dias_antes is None:
        return None
    limite = a_fecha(fecha_limite)
    if limite is None:
        return None
    return (limite - timedelta(days=dias_antes)).isoformat()


def instanciar_en_pursuit(
    *,
    organization_id: int,
    pursuit_id: int,
    actor_user_id: int,
    fecha_limite: Any,
) -> int:
    """Crea las tareas de la plantilla en la oportunidad. Devuelve cuántas.

    ``0`` si la organización no tiene plantilla o si la oportunidad ya la
    recibió. Sin plantilla **no** se reserva el evento: la marca dice «se
    aplicó», y aplicar una lista vacía no es aplicarla.

    Se reserva antes de crear. Si una tarea falla a mitad, las que faltan no
    se reintentan —la marca ya está puesta—, y el log lo dice; es el
    intercambio correcto frente al contrario, que duplicaría la lista entera
    en cada reintento.
    """
    tareas = _tareas_guardadas(organization_id)
    if not tareas:
        return 0
    nueva = _pursuits.reservar_evento_unico(
        organization_id=organization_id,
        pursuit_id=pursuit_id,
        actor_user_id=actor_user_id,
        event_type=EVENTO_PLANTILLA,
        idempotency_key=f"plantilla_tareas:{ETAPA}",
        payload={"origen": "plantilla", "etapa": ETAPA, "tareas": len(tareas)},
    )
    if not nueva:
        return 0

    creadas = 0
    for tarea in tareas:
        try:
            fila = _tareas.create(
                pursuit_id=pursuit_id,
                organization_id=organization_id,
                titulo=tarea.titulo,
                vence=vence_relativo(fecha_limite, tarea.dias_antes_limite),
            )
        except Exception as exc:
            log.warning(
                "plantilla_tarea_no_creada",
                pursuit_id=pursuit_id,
                organization_id=organization_id,
                error=str(exc)[:200],
            )
            continue
        if fila is not None:
            creadas += 1

    if creadas:
        from services.pursuit_tasks import sincronizar_next_action

        sincronizar_next_action(organization_id, pursuit_id)
    log.info(
        "tareas_plantilla_creadas",
        origen="plantilla",
        organization_id=organization_id,
        n=creadas,
    )
    return creadas
