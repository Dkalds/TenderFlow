"""Eventos de contrato derivados de ``licitaciones_history`` (Fase 4).

``licitaciones_history`` guarda, por cada cambio detectado en el upsert, un
snapshot del estado *anterior* y la lista ``changed_fields``. Este módulo
convierte esos diffs en eventos tipados del ciclo de vida del contrato:

- ``estado`` → ADJ: **adjudicacion** · RES: **formalizacion** ·
  ANUL: **anulacion** · resto: **cambio_estado**
- ``importe`` → **modificacion** con ``importe_delta``
- ``fecha_fin`` / ``duracion_*`` → **prorroga** si extiende, **modificacion**
  si recorta; un plazo que pasa de vacío a tener valor no es evento

El valor "después" de un cambio es el snapshot del siguiente registro de
historial de la misma licitación (cada snapshot es el estado previo al
cambio siguiente) o, para el último cambio, la fila actual.

Incremental e idempotente: cursor en ``ingestion_cursors``
(source='contract_events', last_entry_id = último history_id procesado) +
índice único sobre (history_id, tipo, campo).

El SQL —lectura del historial, escritura de eventos, la transacción del lote,
y las lecturas de la línea de tiempo y del feed que sirve ``GET /eventos``—
vive en ``db/contrato_eventos.py`` (ADR-022); aquí queda la clasificación.

Nota: las renovaciones (Fase 2) no necesitan estos eventos para reflejar
prórrogas — la fila actual de licitaciones ya contiene la fecha_fin
extendida. Los eventos aportan el *cuándo y cuánto* del cambio.

**Alertas de expediente seguido (S4.5).** El mismo recorrido emite además un
evento ``licitacion.cambiada`` en el outbox cuando el expediente que cambió lo
sigue alguien: está en los favoritos de un usuario o es una oportunidad abierta
de alguna organización. Se hace aquí, dentro de ``derive_new_events``, y no en
un productor aparte, por dos razones que son la misma: este bucle **ya** tiene
el cursor de ``ingestion_cursors`` que evita releer el historial entero, y
**ya** compara antes/después con ``values_equal``, que es lo que impide que una
re-ingesta sin cambio real genere un aviso. Un segundo productor habría tenido
que duplicar las dos cosas y habrían divergido.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from db.contrato_eventos import (
    en_transaccion,
    estado_actual,
    historial_pendiente,
    insertar_evento,
)
from db.database import get_cursor, set_cursor
from db.events import append_domain_event, seguidores_de_licitacion
from observability.logging import get_logger
from shared.duracion import DIAS_POR_MES, meses_de
from shared.numeric import values_equal

if TYPE_CHECKING:
    # Solo la anotación de la conexión que `en_transaccion` presta al lote.
    from db.connection import _PgConnAdapter

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs — respuesta tipada de GET /eventos (el feed reciente, no la timeline
# por licitación, que sigue siendo dict[str, Any] de forma variable por UNION).
# ---------------------------------------------------------------------------


class EventoFeedItem(BaseModel):
    """Un evento del feed reciente de movimientos de contrato."""

    licitacion_id: str
    tipo: str
    fecha: str | None = None
    detalle: str | None = None
    importe_delta: float | None = None
    titulo: str | None = None
    organo_contratacion: str | None = None
    fuente: str | None = None


class EventosPorTipo(BaseModel):
    """Movimientos de un tipo en la ventana del feed."""

    tipo: str
    n: int


class EventosFeedResult(BaseModel):
    """Respuesta de ``GET /eventos``.

    ``por_tipo`` cuenta **todos** los movimientos de la ventana y el ámbito, por
    tipo y de mayor a menor; ``items`` es solo la página más reciente, con su
    ``limit``. El reparto sale de la misma cláusula que la lista
    (``db.contrato_eventos._filtro_eventos``), así que ``total`` —la suma de ``por_tipo``— es el
    total del que ``items`` es una muestra.
    """

    items: list[EventoFeedItem] = []
    dias: int = 30
    por_tipo: list[EventosPorTipo] = []
    total: int = 0


_CURSOR_SOURCE = "contract_events"

_ESTADO_EVENTO = {
    "ADJ": "adjudicacion",
    "ADJUDICADA": "adjudicacion",
    "RES": "formalizacion",
    "ANUL": "anulacion",
}

# Campos de historial que generan evento (titulo/descripcion son ruido editorial)
_CAMPOS_EVENTO = ("estado", "importe", "fecha_fin", "duracion_valor", "duracion_unidad")

#: Campos cuyo cambio se avisa a quien sigue el expediente (S4.5).
#:
#: Es un superconjunto de :data:`_CAMPOS_EVENTO` con ``fecha_limite``, ``cpv``
#: y ``url``: al seguidor de un expediente le importa sobre todo que le hayan
#: movido el plazo, que es justo el campo que NO genera evento de contrato
#: (mover el plazo no modifica el contrato, modifica la oportunidad). Siguen
#: fuera ``titulo`` y ``descripcion`` por lo mismo que arriba — un retoque de
#: redacción no es una novedad.
_CAMPOS_SEGUIDOS = (
    "estado",
    "importe",
    "fecha_limite",
    "fecha_fin",
    "duracion_valor",
    "duracion_unidad",
    "cpv",
    "url",
)


def _emitir_cambio_seguido(
    conn: Any,
    *,
    id_externo: str,
    history_id: int,
    antes: dict[str, Any],
    despues: dict[str, Any],
    changed: list[str],
) -> bool:
    """Escribe ``licitacion.cambiada`` si el expediente lo sigue alguien.

    Devuelve ``True`` si emitió. Tres cortes, y los tres importan:

    1. Sin campos con cambio **real** (``values_equal``), no hay evento: una
       re-ingesta que reescribe los mismos valores no despierta a nadie.
    2. Sin seguidores, no hay evento. La consulta es lo último que se hace, no
       lo primero, porque el 99% de las filas de historial son de expedientes
       que no sigue nadie y descartarlas por los campos es más barato.
    3. El evento va en la transacción del cursor (``conn``): si la pasada se
       revierte, el aviso se va con ella. Es el outbox, no un efecto lateral.

    Se escribe **un evento por organización**, con ``organization_id`` y solo
    los seguidores de esa organización: el webhook de una organización no
    puede enterarse de quién sigue qué en las demás.
    """
    valores: dict[str, dict[str, Any]] = {}
    for campo in changed:
        if campo not in _CAMPOS_SEGUIDOS:
            continue
        valor_antes = antes.get(campo)
        valor_despues = despues.get(campo)
        if values_equal(valor_antes, valor_despues):
            continue
        valores[campo] = {"antes": valor_antes, "despues": valor_despues}
    if not valores:
        return False

    seguidores = seguidores_de_licitacion(id_externo)
    if not seguidores:
        return False

    from db.users import get_user_by_id
    from shared.identity import user_key_from_email

    resueltos: list[dict[str, Any]] = []
    vistos: set[tuple[str, int]] = set()
    for fila in seguidores:
        organization_id = int(fila.get("organization_id") or 0)
        if not organization_id:
            continue
        user_key = fila.get("user_key")
        bruto = fila.get("user_id")
        user_id = int(bruto) if bruto is not None else None
        if not user_key:
            if user_id is None:
                continue
            usuario = get_user_by_id(user_id)
            if usuario is None:
                continue
            user_key = user_key_from_email(usuario.get("email"), user_id)
        clave = (str(user_key), organization_id)
        if clave in vistos:
            continue
        vistos.add(clave)
        # ``user_id`` viaja en el payload (v129) para que el despachador
        # escriba la alerta con las dos identidades; ``None`` si el favorito
        # no se pudo resolver por email.
        resueltos.append(
            {"user_key": str(user_key), "organization_id": organization_id, "user_id": user_id}
        )

    if not resueltos:
        return False

    # F5.3: el cambio sale con nombre. La clasificación es la misma función
    # pura que usa «desde tu última visita», así que la campana, el digest y
    # el Resumen llaman igual a lo mismo. Se clasifica sobre los campos con
    # cambio real (`valores`), no sobre `changed`, para que un campo que la
    # fuente reescribió con el mismo valor no gane el titular.
    from services.avisos import clasificar_cambio

    aviso = clasificar_cambio(antes, despues, sorted(valores))
    # Un evento por organización, con solo sus seguidores (como
    # `services/avisos_outbox`). Con uno solo y sin dueño, el webhook de cada
    # organización recibía los seguidores de todas las demás.
    for organization_id in sorted({s["organization_id"] for s in resueltos}):
        append_domain_event(
            "licitacion.cambiada",
            id_externo,
            "licitacion",
            {
                "id_externo": id_externo,
                "licitacion_id": id_externo,
                "titulo": despues.get("titulo") or antes.get("titulo"),
                "changed_fields": sorted(valores),
                "valores": valores,
                "history_id": history_id,
                "subtipo": aviso.subtipo,
                "aviso_titulo": aviso.titulo,
                "aviso_detalle": aviso.detalle,
                "organization_id": organization_id,
                "seguidores": [s for s in resueltos if s["organization_id"] == organization_id],
            },
            organization_id=organization_id,
            conn=conn,
        )
    return True


def _classify(
    campo: str,
    antes: Any,
    despues: Any,
    *,
    antes_estado: Mapping[str, Any] | None = None,
    despues_estado: Mapping[str, Any] | None = None,
) -> tuple[str, float | None, str] | None:
    """Devuelve (tipo, importe_delta, detalle) o None si el cambio no es evento.

    ``antes_estado`` y ``despues_estado`` son las filas completas: una duración
    solo se compara con su unidad (24 meses → 3 años amplía, aunque el número baje).
    """
    # Con tolerancia y no `==`: `importe` es `real` en producción y el snapshot
    # de historial puede diferir del valor actual sólo por el redondeo a
    # float4, sin que nadie haya modificado el contrato. Esto además protege
    # de las filas de historial basura escritas antes del fix en db/upsert.py
    # (ver shared/numeric.py): siguen en la tabla y el cursor las procesará.
    if values_equal(antes, despues):
        return None
    if campo == "estado":
        tipo = _ESTADO_EVENTO.get(str(despues or "").upper(), "cambio_estado")
        return tipo, None, f"estado {antes or '—'} → {despues or '—'}"
    if campo == "importe":
        try:
            delta = float(despues) - float(antes)
        except (TypeError, ValueError):
            delta = None
        if not delta:
            return None
        return "modificacion", delta, f"importe {antes} → {despues}"
    if campo in ("fecha_fin", "duracion_valor", "duracion_unidad") and antes in (None, ""):
        # Un plazo que llega por primera vez no amplía ni recorta el contrato.
        return None
    if campo == "fecha_fin":
        if not despues:
            return None
        tipo = "prorroga" if str(despues) > str(antes) else "modificacion"
        return tipo, None, f"fecha_fin {antes or '—'} → {despues}"
    if campo in ("duracion_valor", "duracion_unidad"):
        if despues is None:
            return None
        meses_antes = meses_de(
            (antes_estado or {}).get("duracion_valor"), (antes_estado or {}).get("duracion_unidad")
        )
        meses_despues = meses_de(
            (despues_estado or {}).get("duracion_valor"),
            (despues_estado or {}).get("duracion_unidad"),
        )
        if meses_antes is not None and meses_despues is not None:
            # Menos de un día de diferencia es la misma duración en otra unidad
            # (12 meses → 1 año, 365 días → 1 año), no un cambio de contrato.
            if abs(meses_despues - meses_antes) < 1 / DIAS_POR_MES:
                return None
            tipo = "prorroga" if meses_despues > meses_antes else "modificacion"
        elif campo == "duracion_valor":
            try:
                extiende = float(despues) > float(antes)
            except (TypeError, ValueError):
                extiende = False
            tipo = "prorroga" if extiende else "modificacion"
        else:
            tipo = "modificacion"
        return tipo, None, f"{campo} {antes or '—'} → {despues}"
    return None


def derive_new_events(batch_size: int = 1000) -> int:
    """Deriva eventos de las filas de historial aún no procesadas.

    Devuelve el número de eventos insertados. Pensado para ejecutarse tras
    cada ingesta (fail-open en los llamadores) o manualmente para backfill.
    """
    cursor = get_cursor(_CURSOR_SOURCE)
    last_id = int((cursor or {}).get("last_entry_id") or 0)

    # El lote entero —eventos y avisos del outbox— va en una transacción, que
    # abre `db/` (ADR-022); el cursor avanza después, solo si hubo commit.
    def _derivar_lote(c: _PgConnAdapter) -> tuple[int, int, int] | None:
        rows = historial_pendiente(c, last_id, batch_size)
        if not rows:
            return None

        inserted = 0
        avisados = 0
        max_id = last_id
        # Snapshot parseado de cada fila (``None`` si no parsea), una sola vez,
        # y el índice de la siguiente fila de la misma licitación dentro del
        # lote, en una pasada hacia atrás. Antes cada fila recorría (y copiaba)
        # el resto del lote buscando su siguiente: cuadrático con 1000 filas.
        snapshots: list[dict[str, object] | None] = []
        for row in rows:
            try:
                snapshots.append(json.loads(row["snapshot_json"]))
            except (TypeError, ValueError):
                snapshots.append(None)
        siguiente: list[int | None] = [None] * len(rows)
        ultima_vista: dict[str, int] = {}
        for i in range(len(rows) - 1, -1, -1):
            clave = str(rows[i]["id_externo"])
            siguiente[i] = ultima_vista.get(clave)
            ultima_vista[clave] = i

        for i, row in enumerate(rows):
            max_id = max(max_id, int(row["id"]))
            snapshot = snapshots[i]
            if snapshot is None:
                continue

            # Estado "después": snapshot del siguiente cambio de la misma
            # licitación dentro del lote, o la fila actual de licitaciones.
            j = siguiente[i]
            despues_state: dict[str, Any] | None = snapshots[j] if j is not None else None
            if despues_state is None:
                despues_state = estado_actual(c, str(row["id_externo"]))
                if despues_state is None:
                    continue

            changed = [f.strip() for f in (row["changed_fields"] or "").split(",")]
            if _emitir_cambio_seguido(
                c,
                id_externo=str(row["id_externo"]),
                history_id=int(row["id"]),
                antes=snapshot,
                despues=despues_state,
                changed=changed,
            ):
                avisados += 1
            for campo in changed:
                if campo not in _CAMPOS_EVENTO:
                    continue
                if campo == "duracion_unidad" and "duracion_valor" in changed:
                    # `_classify` compara la duración entera (valor y unidad):
                    # el cambio de los dos campos es un solo evento, no dos.
                    continue
                evento = _classify(
                    campo,
                    snapshot.get(campo),
                    despues_state.get(campo),
                    antes_estado=snapshot,
                    despues_estado=despues_state,
                )
                if evento is None:
                    continue
                tipo, delta, detalle = evento
                antes_valor = snapshot.get(campo)
                despues_valor = despues_state.get(campo)
                insertar_evento(
                    c,
                    licitacion_id=str(row["id_externo"]),
                    tipo=tipo,
                    fecha=str(row["captured_at"])[:10],
                    campo=campo,
                    valor_antes=str(antes_valor) if antes_valor is not None else None,
                    valor_despues=str(despues_valor) if despues_valor is not None else None,
                    importe_delta=delta,
                    detalle=detalle,
                    history_id=int(row["id"]),
                )
                inserted += 1
        return inserted, avisados, max_id

    resultado = en_transaccion(_derivar_lote)
    if resultado is None:
        return 0
    inserted, avisados, max_id = resultado
    set_cursor(_CURSOR_SOURCE, last_entry_id=str(max_id))
    if inserted or avisados:
        log.info(
            "contract_events_derived",
            inserted=inserted,
            cambios_seguidos=avisados,
            hasta_history_id=max_id,
        )
    return inserted
