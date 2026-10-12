"""Respaldo del carril diario: el ZIP mensual cuando el ATOM de PLACSP no avanza.

Por qué existe (backlog P0, medido el 2026-09-24): el feed ATOM
``licitacionesPerfilesContratanteCompleto3.atom`` dejó de publicar entradas
nuevas el 2026-09-08. Su cabecera se regeneraba, pero la entrada más reciente
seguía siendo la del día 8; el cursor ``placsp`` estaba en ese mismo instante,
así que cada pasada leía una entrada, paraba con ``stopped=cursor_reached`` e
ingería 0 avisos **en verde**. El ZIP mensual del mismo mes sí se regeneraba
cada madrugada. El healthcheck ya lo avisa (``sin_datos_nuevos``, umbral
``max_antiguedad_dato_hours`` de 48 h); esto recupera el dato mientras tanto,
con el mismo camino que la recuperación manual (``scrape-bulk.yml months=1``).

**El criterio.** El ATOM «no avanza» cuando una pasada termina sin fallo de
descarga y el ``last_seen_updated`` del cursor ``placsp`` es el mismo antes y
después. Tras ``PLACSP_ATOM_PASADAS_SIN_AVANCE_ZIP`` pasadas seguidas así, el
carril ingiere el ZIP del mes en curso con ``PlacspBulkConnector`` y la cuenta
vuelve a cero. Por qué 6 por defecto:

- El ZIP se regenera **una vez al día**. Con una pasada cada 4 h, 6 pasadas son
  un día: caer antes, o en cada pasada mientras dure, reprocesaría el mismo
  fichero y se comería la ventana del carril para no traer nada nuevo.
- Un feed sano no pasa 4 h sin una sola entrada: el cursor es la entrada más
  reciente de **todo** el país, antes del filtro de tecnología, y en
  condiciones normales va minutos por detrás. Un día entero parado no es un
  falso positivo posible.
- El primer respaldo llega a las 24 h del congelamiento, antes de que el
  healthcheck dé el aviso de las 48 h. El aviso sigue saltando —el ATOM sigue
  roto y eso hay que verlo—; el respaldo solo acota cuánto dato se pierde.

``0`` lo apaga. Si cambia la cadencia del plano, cambia lo que dura una
pasada, no el criterio.

**Qué respeta.**

- *El cursor del ATOM.* El conector bulk escribe con ``fuente = bulk_YYYYMM``
  y no tiene cursor (``new_cursor()`` es ``None``): el de ``placsp`` no se
  toca, y cuando el ATOM vuelva retomará desde donde se paró.
- *La idempotencia.* ``run_connector`` hace upsert con historial: un mismo ZIP
  dos veces no duplica nada, y lo que el ATOM traiga después lo actualiza.
- *La ventana del carril.* El estado se apunta **antes** de bajar el ZIP: si la
  descarga agota el step (45 min), la pasada siguiente no vuelve a intentarlo,
  sino que espera otras N. Y como mucho se procesan dos meses —el anterior
  solo si el hueco empezó en él, para no perder su último día al cambiar de
  mes—: un respaldo no es un backfill.

**Dónde se apunta.** En ``ingestion_cursors``, fila ``placsp_atom_respaldo_zip``
(igual que ``entity_resolution_pscp`` o ``dedupe_<fuente>`` guardan su posición
ahí): ``last_seen_updated`` es el cursor del ATOM que se está viendo parado,
``last_entry_id`` las pasadas seguidas sin avance y ``last_modified`` la fecha
del último respaldo del episodio. Cada respaldo deja además un log
``placsp_atom_respaldo_zip`` y un evento con ese nombre en ``ops_events``.

Lo llama ``scheduler.pipeline_runs._run_daily_pipeline_connector``, que es el
mismo camino en los dos planos (``scrape-daily.yml`` y
``scheduler/jobs/daily_atom.py``). Nunca lanza: un respaldo roto no puede tumbar
una ingesta que ya terminó.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from db.database import get_cursor, set_cursor
from observability.logging import get_logger
from observability.ops_events import record_event

log = get_logger(__name__)

#: Fila de ``ingestion_cursors`` donde vive la cuenta (ver docstring del módulo).
CURSOR_ESTADO = "placsp_atom_respaldo_zip"
#: Cursor del feed ATOM cuyo avance se vigila.
CURSOR_ATOM = "placsp"
#: Evento de ``ops_events`` que deja cada respaldo.
EVENTO_RESPALDO = "placsp_atom_respaldo_zip"


@dataclass(frozen=True)
class EstadoRespaldo:
    """Lo que el carril recuerda entre pasadas del ATOM parado."""

    cursor_atom: str | None = None
    pasadas_sin_avance: int = 0
    ultimo_respaldo: str | None = None

    @classmethod
    def desde_cursor(cls, fila: dict[str, Any] | None) -> EstadoRespaldo:
        if not fila:
            return cls()
        try:
            pasadas = int(str(fila.get("last_entry_id") or 0))
        except ValueError:
            pasadas = 0
        return cls(
            cursor_atom=str(fila.get("last_seen_updated") or "") or None,
            pasadas_sin_avance=max(0, pasadas),
            ultimo_respaldo=str(fila.get("last_modified") or "") or None,
        )


def cursor_atom_actual() -> str | None:
    """El ``last_seen_updated`` del cursor del ATOM, o ``None`` si no hay o no se lee.

    Fail-open como el resto del módulo: si la lectura falla, la pasada cuenta
    como «sin referencia» y el carril sigue.
    """
    try:
        fila = get_cursor(CURSOR_ATOM)
    except Exception as exc:
        log.warning("placsp_atom_respaldo_zip_cursor_ilegible", error=str(exc))
        return None
    return str((fila or {}).get("last_seen_updated") or "") or None


def _mes_anterior(hoy: date) -> tuple[int, int]:
    return (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)


def meses_de_respaldo(hoy: date, desde: str | None) -> list[tuple[int, int]]:
    """El mes en curso y, si lo que falta empezó antes, también el anterior.

    *desde* es la fecha del último respaldo del episodio o, si aún no hubo
    ninguno, el cursor parado del ATOM (cualquier texto que empiece por una
    fecha ISO). Sin el mes anterior, un hueco que cruza el cambio de mes perdía
    su último día: el ZIP del mes en curso trae «hasta ayer», y el día 1 ese
    ayer es del mes pasado. Más atrás no se va —eso es un backfill, y tiene su
    workflow—. Orden ascendente, como el backfill: si un expediente aparece en
    los dos ZIP, gana el último escrito, que es el más reciente.
    """
    actual = (hoy.year, hoy.month)
    try:
        inicio = date.fromisoformat(str(desde or "")[:10])
    except ValueError:
        return [actual]
    if (inicio.year, inicio.month) < actual:
        return [_mes_anterior(hoy), actual]
    return [actual]


def _correr_mes(year: int, month: int) -> dict[str, Any]:
    """Ingiere el ZIP de un mes con el conector bulk, como ``scrape-bulk.yml``."""
    from scraper.connectors.base import run_connector
    from scraper.connectors.placsp import PlacspBulkConnector

    resultado = run_connector(PlacspBulkConnector(year, month))
    return {
        "year": year,
        "month": month,
        "status": "error" if resultado.fetch_failed else "ok",
        "nuevas": resultado.nuevas,
        "actualizadas": resultado.actualizadas,
        "adjudicaciones": resultado.adjudicaciones,
    }


def _guardar(estado: EstadoRespaldo) -> None:
    set_cursor(
        CURSOR_ESTADO,
        last_seen_updated=estado.cursor_atom,
        last_entry_id=str(estado.pasadas_sin_avance),
        last_modified=estado.ultimo_respaldo,
    )


def tras_pasada_atom(
    *,
    cursor_antes: str | None,
    cursor_despues: str | None,
    fetch_failed: bool,
    umbral: int | None = None,
    hoy: date | None = None,
    correr_mes: Callable[[int, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Cuenta la pasada del ATOM y, si toca, cae al ZIP del mes. Nunca lanza.

    Devuelve un resumen con ``accion``: ``desactivado`` (umbral 0),
    ``fallo_fetch`` (la descarga falló: caído no es congelado, y el ZIP vive en
    el mismo host), ``sin_referencia`` (no había cursor antes), ``avanza``,
    ``cuenta`` (parado, aún por debajo del umbral), ``respaldo`` o ``error``.
    *umbral*, *hoy* y *correr_mes* existen para los tests.
    """
    if umbral is None:
        from config import settings

        umbral = settings.PLACSP_ATOM_PASADAS_SIN_AVANCE_ZIP
    if umbral <= 0:
        return {"accion": "desactivado"}
    try:
        return _tras_pasada(
            cursor_antes=cursor_antes,
            cursor_despues=cursor_despues,
            fetch_failed=fetch_failed,
            umbral=umbral,
            hoy=hoy or datetime.now(UTC).date(),
            correr_mes=correr_mes or _correr_mes,
        )
    except Exception as exc:
        log.warning("placsp_atom_respaldo_zip_fallido", error=str(exc), exc_info=True)
        return {"accion": "error", "error": str(exc)[:200]}


def _tras_pasada(
    *,
    cursor_antes: str | None,
    cursor_despues: str | None,
    fetch_failed: bool,
    umbral: int,
    hoy: date,
    correr_mes: Callable[[int, int], dict[str, Any]],
) -> dict[str, Any]:
    estado = EstadoRespaldo.desde_cursor(get_cursor(CURSOR_ESTADO))
    if fetch_failed:
        return {"accion": "fallo_fetch", "pasadas_sin_avance": estado.pasadas_sin_avance}
    if cursor_antes is None:
        return {"accion": "sin_referencia"}
    if cursor_despues is not None and cursor_despues > cursor_antes:
        if estado.pasadas_sin_avance or estado.ultimo_respaldo:
            _guardar(EstadoRespaldo(cursor_atom=cursor_despues))
        return {"accion": "avanza"}

    # Parado. Mismo instante que el episodio en curso → suma; otro → empieza.
    mismo_episodio = estado.cursor_atom == cursor_antes
    pasadas = estado.pasadas_sin_avance + 1 if mismo_episodio else 1
    ultimo = estado.ultimo_respaldo if mismo_episodio else None
    if pasadas < umbral:
        _guardar(EstadoRespaldo(cursor_antes, pasadas, ultimo))
        log.info("placsp_atom_sin_avance", cursor_atom=cursor_antes, pasadas=pasadas, umbral=umbral)
        return {"accion": "cuenta", "pasadas_sin_avance": pasadas, "umbral": umbral}

    meses = meses_de_respaldo(hoy, ultimo or cursor_antes)
    etiquetas = [f"{year}-{month:02d}" for year, month in meses]
    # Antes de bajar nada: ver «La ventana del carril» en el docstring.
    _guardar(EstadoRespaldo(cursor_antes, 0, hoy.isoformat()))
    log.warning(
        "placsp_atom_respaldo_zip",
        cursor_atom=cursor_antes,
        pasadas=pasadas,
        umbral=umbral,
        meses=etiquetas,
    )
    record_event(
        EVENTO_RESPALDO,
        value=len(meses),
        detail=f"cursor_atom={cursor_antes};pasadas={pasadas};meses={','.join(etiquetas)}",
    )
    resultados: list[dict[str, Any]] = []
    for year, month in meses:
        try:
            resultados.append(correr_mes(year, month))
        except Exception as exc:
            log.warning(
                "placsp_atom_respaldo_zip_mes_fallido", year=year, month=month, error=str(exc)
            )
            resultados.append({"year": year, "month": month, "status": "error"})
    return {
        "accion": "respaldo",
        "pasadas_sin_avance": pasadas,
        "umbral": umbral,
        "meses": etiquetas,
        "resultados": resultados,
    }
