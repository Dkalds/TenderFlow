"""Programación del informe por organización (`organization_report_schedules`, v132).

Todo el SQL de la tabla vive aquí (ADR-022). La lógica de qué lleva el informe
está en ``services/informes.py``; lo de aquí es día, hora, destinatarios y la
marca del último envío.

La idempotencia se decide en el SQL, no en el job
-------------------------------------------------
:func:`pendientes` no devuelve «las programaciones de hoy a esta hora»: devuelve
las que tocan **y todavía no se han enviado en esta ventana**. La diferencia
importa porque el paso corre en **cada pasada de la pipeline** —cada cuatro
horas, y varias veces si alguien relanza—, no una vez al día. Con el filtro en
el job, dos pasadas dentro de la misma hora mandarían el informe dos veces; con
el filtro aquí, la segunda no ve la fila.

El predicado es ``ultimo_envio_at < inicio_de_la_ventana``, y la ventana es el
día programado a la hora programada. Se compara contra un instante calculado en
Python y pasado como parámetro en vez de derivarlo con `now()` en SQL: así el
test puede fijar «ahora» sin tocar el reloj de la base.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

#: Espejo del `CHECK` de v132.
TIPOS: frozenset[str] = frozenset({"pipeline_semanal"})

#: **0 = lunes**, como `EXTRACT(ISODOW) - 1` y como `datetime.weekday()`. No es
#: el `DOW` de Postgres (0 = domingo): mezclarlos desplaza el informe seis días.
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

_COLS = (
    "id, organization_id, tipo, activo, dia_semana, hora_utc, destinatarios_json, "
    "ultimo_envio_at, ultimo_estado, created_at, updated_at"
)


def _fila(row: dict[str, Any]) -> dict[str, Any]:
    """Normaliza para el DTO: fechas a ISO y la lista de correos a `list[str]`."""
    salida = dict(row)
    for campo in ("ultimo_envio_at", "created_at", "updated_at"):
        valor = salida.get(campo)
        if isinstance(valor, datetime):
            salida[campo] = valor.isoformat()
    crudo = salida.pop("destinatarios_json", None)
    destinatarios: list[str] | None = None
    if crudo:
        try:
            cargado = json.loads(crudo)
            destinatarios = [str(x) for x in cargado] if isinstance(cargado, list) else None
        except (TypeError, ValueError):
            # Un JSON corrupto no puede impedir leer la programación: se trata
            # como «sin lista», que cae en los owner/admin de la organización.
            log.warning("report_schedule_destinatarios_invalidos", schedule_id=salida.get("id"))
    salida["destinatarios"] = destinatarios
    return salida


def inicio_de_ventana(ahora: datetime, *, dia_semana: int, hora_utc: int) -> datetime:
    """Instante en que empezó la ventana de esta semana para ``(día, hora)``.

    Si todavía no ha llegado esta semana, devuelve la de la **semana pasada**:
    así el llamante compara siempre contra una ventana ya abierta y no tiene
    que distinguir «aún no toca» de «ya se envió».
    """
    candidato = (ahora - timedelta(days=(ahora.weekday() - dia_semana) % 7)).replace(
        hour=hora_utc, minute=0, second=0, microsecond=0
    )
    return candidato - timedelta(days=7) if candidato > ahora else candidato


def get(organization_id: int, *, tipo: str = "pipeline_semanal") -> dict[str, Any] | None:
    with connect_read() as c:
        filas = rows_to_dicts(
            c.execute(
                f"SELECT {_COLS} FROM organization_report_schedules "
                "WHERE organization_id = %s AND tipo = %s",
                (organization_id, tipo),
            )
        )
    return _fila(filas[0]) if filas else None


def guardar(
    organization_id: int,
    *,
    tipo: str = "pipeline_semanal",
    activo: bool,
    dia_semana: int,
    hora_utc: int,
    destinatarios: list[str] | None,
) -> dict[str, Any]:
    """Alta o edición de la programación. Una fila por organización y tipo.

    **No toca `ultimo_envio_at`.** Cambiar el día o la hora no puede volver a
    mandar un informe que ya salió: quien mueve la programación del lunes al
    martes no está pidiendo dos informes esta semana.
    """
    crudo = json.dumps(destinatarios, ensure_ascii=False) if destinatarios else None
    with connect() as c:
        filas = rows_to_dicts(
            c.execute(
                "INSERT INTO organization_report_schedules "
                " (organization_id, tipo, activo, dia_semana, hora_utc, destinatarios_json, "
                "  updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, now()) "
                "ON CONFLICT ON CONSTRAINT uq_report_schedule_org_tipo DO UPDATE SET "
                " activo = EXCLUDED.activo, dia_semana = EXCLUDED.dia_semana, "
                " hora_utc = EXCLUDED.hora_utc, "
                " destinatarios_json = EXCLUDED.destinatarios_json, updated_at = now() "
                f"RETURNING {_COLS}",
                (organization_id, tipo, activo, dia_semana, hora_utc, crudo),
            )
        )
    return _fila(filas[0])


def pendientes(ahora: datetime | None = None) -> list[dict[str, Any]]:
    """Programaciones activas cuya ventana está abierta y sin enviar.

    Ver la cabecera del módulo: el filtro de «ya enviado» va aquí y no en el
    job, porque el paso corre varias veces dentro de la misma ventana.
    """
    instante = (ahora or datetime.now(UTC)).astimezone(UTC)
    with connect_read() as c:
        filas = rows_to_dicts(
            c.execute(
                # El filtro es sólo `activo` (índice parcial de v132) y la
                # ventana se decide en Python. Filtrar además por
                # `hora_utc <= EXTRACT(HOUR)` parecía barato y estaba **mal**:
                # una programación de los lunes a las 20:00 desaparecía en la
                # pasada de las 03:00 del martes, que es exactamente cuando su
                # ventana sigue abierta. La tabla tiene como mucho una fila por
                # organización activa, así que no hay nada que optimizar aquí.
                # **Sin `LIMIT`**, y el motivo merece quedar escrito porque se
                # intentó dos veces al revés. El tope se aplica en SQL y la
                # ventana se decide en Python, así que cualquier tope corta
                # antes de saber a quién le toca: con `ORDER BY
                # organization_id` las organizaciones de id alto no recibían
                # informe **nunca**, y cambiarlo a `ultimo_envio_at NULLS
                # FIRST` sólo movió la inanición —una organización cuyo envío
                # falla siempre se queda con `ultimo_envio_at` a NULL y ocupa
                # la cabeza de la lista para siempre—.
                #
                # La tabla tiene como mucho una fila por organización **con el
                # informe activo**, y son filas pequeñas. Leerlas todas es más
                # barato que el fallo silencioso que evita.
                f"SELECT {_COLS} FROM organization_report_schedules "
                "WHERE activo ORDER BY organization_id",
                (),
            )
        )

    listas: list[dict[str, Any]] = []
    for cruda in filas:
        fila = _fila(cruda)
        ventana = inicio_de_ventana(
            instante, dia_semana=int(fila["dia_semana"]), hora_utc=int(fila["hora_utc"])
        )
        # La ventana abierta tiene que ser la de **esta** semana: la de hace
        # siete días significa que hoy no es el día programado.
        if (instante - ventana) >= timedelta(days=1):
            continue
        ultimo = fila.get("ultimo_envio_at")
        if ultimo and datetime.fromisoformat(str(ultimo)) >= ventana:
            continue
        listas.append(fila)
    return listas


def marcar_estado(schedule_id: int, *, estado: str) -> None:
    """Deja constancia de lo que pasó **sin cerrar la ventana**.

    Separado de :func:`marcar_envio` porque son dos cosas distintas que antes
    iban juntas: `ultimo_estado` es diagnóstico —lo lee quien pregunta «¿por
    qué no me llegó?»— y `ultimo_envio_at` es el cierre de la ventana, que
    impide reintentar.

    Cuando el proveedor de correo falla hay que escribir lo primero y no lo
    segundo: si se sella, la organización se queda sin informe esa semana; si
    no se deja constancia, `ultimo_estado` sigue mostrando el `enviado:3/3` de
    la semana pasada y le dice a quien mira que el correo salió.
    """
    with connect() as c:
        c.execute(
            "UPDATE organization_report_schedules "
            "SET ultimo_estado = %s, updated_at = now() WHERE id = %s",
            (estado[:60], schedule_id),
        )


def marcar_envio(schedule_id: int, *, estado: str) -> None:
    """Sella el envío (o su ausencia) para que la ventana quede cerrada.

    Se llama **también cuando no se envía nada** —organización sin
    oportunidades, destinatarios todos dados de baja—: si sólo se sellara el
    éxito, esos casos se recalcularían en cada pasada de la pipeline durante
    toda la semana.
    """
    with connect() as c:
        c.execute(
            "UPDATE organization_report_schedules "
            "SET ultimo_envio_at = %s, ultimo_estado = %s, updated_at = now() WHERE id = %s",
            (now_utc_iso(), estado[:60], schedule_id),
        )
