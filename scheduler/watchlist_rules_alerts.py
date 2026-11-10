"""Job de alertas para las reglas de watchlist por criterio (mi-watchlist).

Para cada regla **activa** que este "due" segun su frecuencia
(``immediate``/``daily``/``weekly``), busca licitaciones nuevas (con
``fecha_publicacion`` posterior a ``last_notified_at``, menos la gracia) que
coincidan con sus criterios y escribe **un** ``watchlist_rule.matched`` en el
outbox (``domain_events``, ADR-027). Lo reparte
``scheduler/jobs/event_dispatch.py``, que en el cierre corre después de este
paso y antes de ``digests``:

1. la campana: una fila de ``user_notifications`` por licitación, con
   ``rule_id``;
2. el correo: ``pending_digests`` con la frecuencia y el correo de la regla,
   leídos de la regla al despachar (no viajan en el evento, que también sale
   por webhook);
3. los webhooks suscritos.

Hasta 2026-11 este job escribía la campana y el digest a mano y el evento
solo llevaba el webhook.

Espeja ``scheduler/watchlist_alerts.py`` (watchlist de instancia) pero sobre la
tabla ``watchlist_rules`` (RFC ux-mi-watchlist, increment 4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from db.events import agregados_pendientes, append_domain_event
from db.repositories.watchlist_rules import filas_de_reglas_a_evaluar, marcar_regla_notificada
from observability import get_logger
from services.watchlist_rules import WatchlistRule, matches_since
from shared.dates import instante_utc
from shared.types import JsonDict

log = get_logger(__name__)

# Ventana inicial cuando la regla nunca notifico.
_LOOKBACK_DAYS = 30
# Intervalo minimo entre alertas segun frecuencia (``immediate`` no espera).
_FREQ_INTERVAL = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}

#: Días que la ventana de búsqueda retrocede sobre la última notificación.
#:
#: Dos, y no cero, porque ``fecha_publicacion`` es un día y la ventana avanza a
#: una hora: sin solape, lo ingerido después de la evaluación del día se perdía
#: para siempre. Y dos, y no diez, porque el solape solo es gratis mientras el
#: anti-join contra ``user_notifications`` pueda descartarlo con el índice
#: único; una ventana muy larga acabaría pagando el escaneo sin cubrir ningún
#: caso nuevo — la ingesta tardía real es de horas, no de días.
_VENTANA_GRACIA_DIAS = 2

#: El evento de una regla con matches nuevos, con la regla como agregado.
_EVENTO = "watchlist_rule.matched"
_AGREGADO = "watchlist_rule"


def _is_due(row: dict[str, Any], now: datetime) -> bool:
    """La regla debe evaluarse ya, segun su frecuencia y ultima notificacion?"""
    last = row.get("last_notified_at")
    if not last:
        return True
    freq = row.get("frequency") or "daily"
    if freq == "immediate":
        return True
    interval = _FREQ_INTERVAL.get(freq, _FREQ_INTERVAL["daily"])
    last_dt = instante_utc(last)
    if last_dt is None:
        return True
    return (now - last_dt) >= interval


def _since_date(row: dict[str, Any], default_since: str) -> str:
    """Fecha desde la que buscar matches: la última notificación menos la gracia.

    El corte no puede ser la fecha exacta de la última notificación. ``since``
    se compara contra ``fecha_publicacion``, que tiene granularidad de día,
    mientras que la ventana avanza a la hora en que corre el job: un expediente
    publicado el día D pero ingerido después de la evaluación de ese día caía
    fuera de la ventana siguiente y no volvía a entrar nunca.

    Restar :data:`_VENTANA_GRACIA_DIAS` hace que la ventana **se solape a
    propósito**. Volver a mirar dos días no cuesta nada —el anti-join de
    ``matches_since`` descarta lo ya notificado antes de gastar el ``LIMIT``— y
    a cambio cubre tanto la ingesta tardía del mismo día como la de la víspera,
    que es la que producen los conectores que corren después del carril diario.
    """
    last = row.get("last_notified_at")
    if not last:
        return default_since
    ultimo = instante_utc(last)
    if ultimo is None:
        # Marca ilegible: se cae al lookback largo en vez de inventar un corte.
        # Con el anti-join, mirar de más es barato; mirar de menos pierde avisos.
        return default_since
    return (ultimo - timedelta(days=_VENTANA_GRACIA_DIAS)).date().isoformat()


def _row_to_rule(row: dict[str, Any]) -> WatchlistRule:
    return WatchlistRule(
        id=row.get("id"),
        nombre=row.get("nombre"),
        keyword=row.get("keyword"),
        cpv=row.get("cpv"),
        min_importe=row.get("min_importe"),
        ccaa=row.get("ccaa"),
        frequency=row.get("frequency") or "daily",
        active=True,
        organization_id=row.get("organization_id"),
        visibility=row.get("visibility") or "private",
        tecnologia=row.get("tecnologia"),
        organo=row.get("organo"),
        procedimiento=row.get("procedimiento"),
        tipo_contrato=row.get("tipo_contrato"),
        banda_min=row.get("banda_min"),
        plazo_min_dias=row.get("plazo_min_dias"),
    )


def _build_body(rule: WatchlistRule, matches: list[dict[str, Any]]) -> str:
    """Texto del cuerpo para email / in-app."""
    crit: list[str] = []
    if rule.keyword:
        crit.append(f"keyword: {rule.keyword}")
    if rule.cpv:
        crit.append(f"CPV: {rule.cpv}")
    if rule.min_importe:
        crit.append(f"importe >= {rule.min_importe:,.0f} EUR")
    if rule.ccaa:
        crit.append(f"CCAA: {rule.ccaa}")
    header = rule.nombre or " | ".join(crit) or "tu regla"
    lines = [f"{len(matches)} licitacion(es) nueva(s) para <<{header}>>:\n"]
    for lic in matches[:10]:
        importe = f"{lic['importe']:,.0f} EUR" if lic.get("importe") else "---"
        url = lic.get("url") or ""
        lines.append(
            f"  * [{lic.get('fecha_publicacion', '?')}] {lic.get('titulo', '?')} | {importe}\n"
            f"    {url}"
        )
    if len(matches) > 10:
        lines.append(f"  ... y {len(matches) - 10} mas.")
    return "\n".join(lines)


def check_rules_and_notify(*, limit_per_rule: int = 50) -> int:
    """Evalua las reglas activas "due" y escribe un evento por regla con matches nuevos.

    Returns:
        Numero de reglas que emitieron su ``watchlist_rule.matched``.
    """
    now = datetime.now(UTC)
    now_ts = now.isoformat()
    default_since = (now - timedelta(days=_LOOKBACK_DAYS)).date().isoformat()

    rules = filas_de_reglas_a_evaluar()
    if not rules:
        log.debug("watchlist_rules_empty")
        return 0

    en_cola = agregados_pendientes(_EVENTO, _AGREGADO)
    alerted = 0
    for row in rules:
        try:
            alerted += _evaluar_regla(row, now, now_ts, default_since, limit_per_rule, en_cola)
        except Exception:
            # Una regla que falla no puede bloquear a las demás. Su ventana no
            # avanzó (ver `_evaluar_regla`), así que la siguiente pasada la
            # reintenta.
            log.error("watchlist_rule_fallo", rule_id=row.get("id"), exc_info=True)

    return alerted


def _evaluar_regla(
    row: JsonDict,
    now: datetime,
    now_ts: str,
    default_since: str,
    limit_per_rule: int,
    en_cola: set[str],
) -> bool:
    """Evalúa una regla; ``True`` si emitió su evento.

    La ventana (``last_notified_at``) avanza **después** de escribir el evento:
    si la escritura falla, la regla sigue pendiente y la pasada siguiente busca
    lo mismo.

    Una regla con su aviso anterior aún en cola (``en_cola``) no se evalúa: el
    anti-join de ``matches_since`` mira la campana, que escribe el despachador,
    así que reevaluarla antes emitiría las mismas licitaciones otra vez y el
    webhook las recibiría dos veces. Con el cierre canónico el despacho corre
    en la misma pasada y esto no pasa; la guarda cubre el despachador apagado,
    caído o con la cola por encima del lote. Tampoco avanza su ventana: lo que
    se publique mientras tanto entra en la evaluación siguiente.
    """
    if not _is_due(row, now):
        return False
    rule_id = int(row["id"])
    if str(rule_id) in en_cola:
        log.info("watchlist_rule_aviso_en_cola", rule_id=rule_id)
        return False
    raw_user_id = row.get("user_id")
    if raw_user_id is None:
        # Regla de una clave que ningún usuario conserva (el backfill de v181 no
        # le encontró dueño): sin id no hay anti-join contra la campana, y sin
        # él cada pasada volvería a emitir lo mismo. No avanza su ventana.
        log.warning("watchlist_rule_sin_usuario", rule_id=rule_id)
        return False
    rule = _row_to_rule(row)
    user_id = int(raw_user_id)
    new_matches = matches_since(
        rule,
        _since_date(row, default_since),
        limit=limit_per_rule,
        user_id=user_id,
    )
    if len(new_matches) >= limit_per_rule:
        # La página se llenó: hay más matches de los que caben en una
        # evaluación. No se pierden —el anti-join hace que la siguiente
        # empiece por los que quedaron— pero conviene que se vea, porque
        # una regla que satura el tope cada día es una regla mal acotada.
        log.warning("watchlist_rule_matches_truncados", rule_id=rule_id, limit=limit_per_rule)
    if not new_matches:
        # Mover la ventana aunque no haya matches, para no re-escanear. Es
        # seguro justo porque el corte ya no es lo que decide qué es nuevo: la
        # ventana se solapa y la deduplicación la hace el anti-join.
        marcar_regla_notificada(rule_id, now_ts)
        return False

    # Sin correo ni frecuencia: los lee el despachador de la regla. El payload
    # es también el cuerpo del webhook de la organización.
    append_domain_event(
        _EVENTO,
        rule_id,
        _AGREGADO,
        {
            "rule_id": rule_id,
            "user_key": str(row["user_key"]),
            "nombre": rule.nombre,
            "keyword": rule.keyword,
            "cpv": rule.cpv,
            "total_matches": len(new_matches),
            "licitaciones": [lic.get("id_externo") for lic in new_matches],
        },
        organization_id=rule.organization_id,
    )
    marcar_regla_notificada(rule_id, now_ts)

    log.info("watchlist_rule_alert", rule_id=rule_id, total=len(new_matches))
    return True
