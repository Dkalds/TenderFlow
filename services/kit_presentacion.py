"""F2.3 — qué documentos hay que entregar, y cuáles llevo.

El checklist de capacidad (v2 S2.3) responde «¿cumplimos los requisitos?». Esa
no es la pregunta de quien monta la oferta administrativa tres días antes del
cierre, que es «¿qué papeles tengo que meter en cada sobre y cuáles me
faltan?». Nadie la respondía, y la respuesta estaba en el pliego, sin extraer.

Lo que este módulo **no** hace
------------------------------
No propone una lista genérica. Si el extractor no encontró documentos, el kit
sale vacío y lo dice. Un DEUC y una declaración responsable aparecen en casi
todos los pliegos, y por eso mismo sugerirlos «por defecto» sería el error más
caro posible: el usuario los daría por leídos del pliego, y el que de verdad
importa —la muestra, el compromiso de UTE, la visita obligatoria— seguiría sin
aparecer.

Dónde vive el estado
--------------------
En ``pursuit_events``, con tipo ``kit_item_marcado``. Es un ledger append-only
(v61), así que marcar y desmarcar son dos eventos y el estado actual es el
último de cada ítem. Eso da gratis el «quién marcó qué y cuándo», que en un
equipo que se reparte la oferta es la mitad del valor del checklist — y no
habría forma de tenerlo con una columna booleana.

El responsable
--------------
El plan dejaba el kit sin responsable hasta que existieran las tareas de
oportunidad (C6.1). Ya existen, así que el responsable de un documento **es**
el de su tarea: asignar un ítem crea una tarea en ``pursuit_tasks`` y anota en
el mismo ledger ``{"clave", "tarea_id"}``. No hay un segundo campo
«responsable del kit» que mantener sincronizado con la tarea: si alguien la
reasigna o la borra desde la lista de tareas, el kit lo refleja en la
siguiente lectura.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from shared.tender_facts import RequiredDocumentFact

log = get_logger(__name__)

_repo = PursuitRepository()

__all__ = [
    "EVENTO_KIT",
    "ItemKit",
    "KitPresentacion",
    "anotar_tarea",
    "construir_kit",
    "marcar_item",
    "reducir_eventos",
]

#: Tipo de evento en el ledger. Se re-exporta del repositorio —donde vive el
#: SQL que lo escribe y lo lee (ADR-022)— para que el escritor y el lector no
#: puedan usar dos cadenas distintas: un typo ahí daría un kit que se marca y
#: no se recuerda.
EVENTO_KIT = PursuitRepository.KIT_EVENT_TYPE

#: Orden de los sobres tal como se preparan. El A se hace una vez y se
#: reutiliza; el C se escribe para cada licitación. Presentarlos en otro orden
#: —o alfabético— rompe el orden de ataque real.
ORDEN_SOBRES: tuple[str, ...] = ("sobre_a", "sobre_b", "sobre_c", "otro")

EtiquetaSobre = Literal["sobre_a", "sobre_b", "sobre_c", "otro"]


class ItemKit(BaseModel):
    """Un documento del kit, con su estado y quién lo marcó."""

    model_config = ConfigDict(extra="forbid")

    #: Identificador estable del ítem dentro de la ficha. Es el índice y el
    #: nombre normalizado, no un id de fila: la ficha se re-extrae y una clave
    #: sintética se perdería en cada reproceso, dejando el checklist en blanco.
    clave: str
    nombre: str
    sobre: EtiquetaSobre
    subsanable: bool | None = None
    listo: bool = False
    #: Quién lo marcó por última vez, y cuándo. `None` si nadie lo ha tocado.
    marcado_por: int | None = None
    marcado_en: str | None = None
    #: Tarea (C6.1) que lleva este documento, si se asignó. Los tres campos
    #: siguientes salen de la tarea viva, no de una copia: `None` si nunca se
    #: asignó o si la tarea se borró después.
    tarea_id: int | None = None
    responsable_user_id: int | None = None
    responsable_name: str | None = None
    tarea_estado: str | None = None
    tarea_vence: str | None = None


class KitPresentacion(BaseModel):
    """El kit completo de una oportunidad."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    items: list[ItemKit] = Field(default_factory=list)
    #: `True` cuando el extractor no encontró ningún documento exigido. La UI
    #: lo dice explícitamente en vez de enseñar una lista vacía, que se lee
    #: como que la pieza está rota.
    sin_extraccion: bool = False

    @property
    def listos(self) -> int:
        return sum(1 for item in self.items if item.listo)


def clave_de(indice: int, documento: RequiredDocumentFact) -> str:
    """Clave estable de un ítem: posición y nombre plegado.

    Lleva el índice **y** el nombre porque ninguno de los dos basta solo: el
    índice cambia si el extractor reordena, y el nombre puede repetirse
    («certificado» aparece tres veces con matices distintos). Juntos aguantan
    un reproceso que no cambie el contenido, que es el caso normal.
    """
    normalizado = "-".join(documento.name.lower().split())[:80]
    return f"{indice}:{normalizado}"


def _estado_actual(organization_id: int, pursuit_id: int) -> dict[str, dict[str, Any]]:
    """El último evento por clave de ítem. El ledger es append-only.

    El SQL vive en el repositorio (invariante 10); aquí sólo queda la
    reducción, que es regla de dominio: «el último evento de cada clave manda».
    """
    return reducir_eventos(_repo.kit_events(organization_id, pursuit_id))


def reducir_eventos(filas: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Estado por clave a partir de los eventos del ledger, en orden.

    Hay dos clases de evento bajo el mismo tipo: el marcado (``listo``) y la
    asignación (``tarea_id``). Cada uno pisa **sólo lo suyo**: asignar un
    documento que ya estaba listo no puede desmarcarlo, y marcarlo no puede
    soltar la tarea. Con un último-evento-manda a secas, cualquiera de las dos
    acciones borraba la otra en silencio.
    """
    estado: dict[str, dict[str, Any]] = {}
    for fila in filas:
        try:
            payload = json.loads(str(fila["payload_json"]))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        clave = str(payload.get("clave") or "")
        if not clave:
            continue
        actual = estado.setdefault(clave, {})
        if "listo" in payload:
            actual["listo"] = bool(payload.get("listo"))
            actual["marcado_por"] = fila.get("actor_user_id")
            actual["marcado_en"] = str(fila.get("created_at") or "") or None
        tarea = payload.get("tarea_id")
        if isinstance(tarea, int) and not isinstance(tarea, bool) and tarea > 0:
            actual["tarea_id"] = tarea
    return estado


def construir_kit(
    licitacion_id: str,
    documentos: list[RequiredDocumentFact],
    *,
    organization_id: int | None = None,
    pursuit_id: int | None = None,
    tareas: dict[int, dict[str, Any]] | None = None,
) -> KitPresentacion:
    """El kit, con el estado de la oportunidad si la hay.

    Sin ``pursuit_id`` devuelve la lista sin marcar: la ficha del expediente
    puede enseñar qué documentos exige el pliego aunque nadie haya abierto
    todavía una oportunidad.

    ``tareas`` son las tareas **vivas** de la oportunidad por id. Un ítem cuya
    tarea ya no está ahí sale sin responsable: la tarea se borró y enseñar a
    quien la tenía sería afirmar un reparto que el equipo deshizo.
    """
    if not documentos:
        return KitPresentacion(licitacion_id=licitacion_id, sin_extraccion=True)

    estado: dict[str, dict[str, Any]] = {}
    if organization_id is not None and pursuit_id is not None:
        try:
            estado = _estado_actual(organization_id, pursuit_id)
        except Exception as exc:
            # El kit sin marcas sigue siendo útil; sin kit no hay nada.
            log.warning("kit_estado_error", error=str(exc)[:200])

    items: list[ItemKit] = []
    for indice, documento in enumerate(documentos):
        clave = clave_de(indice, documento)
        marca = estado.get(clave, {})
        tarea = (tareas or {}).get(int(marca.get("tarea_id") or 0))
        items.append(
            ItemKit(
                clave=clave,
                nombre=documento.name,
                sobre=documento.scope,
                subsanable=documento.subsanable,
                listo=bool(marca.get("listo")),
                marcado_por=marca.get("marcado_por"),
                marcado_en=marca.get("marcado_en"),
                tarea_id=int(tarea["id"]) if tarea else None,
                responsable_user_id=tarea.get("responsable_user_id") if tarea else None,
                responsable_name=tarea.get("responsable_name") if tarea else None,
                tarea_estado=str(tarea.get("estado")) if tarea else None,
                tarea_vence=(str(tarea["vence"]) if tarea and tarea.get("vence") else None),
            )
        )

    items.sort(key=lambda i: (ORDEN_SOBRES.index(i.sobre), i.clave))
    return KitPresentacion(licitacion_id=licitacion_id, items=items)


def marcar_item(
    *,
    organization_id: int,
    pursuit_id: int,
    actor_user_id: int,
    clave: str,
    listo: bool,
) -> None:
    """Anota en el ledger que alguien marcó (o desmarcó) un ítem.

    No hay ``UPDATE``: el ledger es append-only por trigger (v61) y desmarcar
    es un evento más. Así el historial responde «¿quién dijo que la garantía
    estaba lista?», que es la pregunta que se hace el día que no está.
    """
    _repo.append_kit_event(
        organization_id=organization_id,
        pursuit_id=pursuit_id,
        actor_user_id=actor_user_id,
        payload={"clave": clave, "listo": listo},
    )


def anotar_tarea(
    *,
    organization_id: int,
    pursuit_id: int,
    actor_user_id: int,
    clave: str,
    tarea_id: int,
) -> None:
    """Ata un documento del kit a la tarea que lo lleva. Sin ``listo``.

    El payload no lleva ``listo`` a propósito: :func:`reducir_eventos` sólo
    toca el marcado cuando el evento lo trae, así que asignar no desmarca.
    """
    _repo.append_kit_event(
        organization_id=organization_id,
        pursuit_id=pursuit_id,
        actor_user_id=actor_user_id,
        payload={"clave": clave, "tarea_id": tarea_id},
    )
