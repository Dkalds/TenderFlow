"""F5.4 — qué ha cambiado desde tu última visita.

Quien entra una vez al día no quiere el catálogo: quiere saber qué se movió en
lo suyo desde ayer. El Resumen tiene «novedades de mercado» —expedientes
nuevos del corpus— y eso responde a otra pregunta: qué hay de nuevo en el
mundo, no qué ha pasado con **mis** expedientes, **mis** pliegos y el pipeline
de **mi equipo**.

Cuatro fuentes, un solo diff
----------------------------
Cambios en lo seguido (F5.3, ya nombrados), documentos nuevos (F5.1), recursos
resueltos (F5.2) y oportunidades del equipo que se movieron. Se fusionan y se
ordenan por fecha, porque el usuario piensa en «qué ha pasado», no en «qué ha
pasado en cada una de las cuatro tablas».

Cero ítems no es una banda vacía
--------------------------------
Con nada que contar, la respuesta dice explícitamente que no ha cambiado nada
desde la última visita. Una banda vacía se lee como que la pieza está rota;
«sin novedades desde el jueves» se lee como lo que es, y además confirma que
el producto estaba mirando.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from db.repositories.novedades import NovedadesRepository
from observability.logging import get_logger
from services.avisos import Aviso, aviso_documento_nuevo, aviso_recurso, clasificar_cambio

log = get_logger(__name__)

_repo = NovedadesRepository()

__all__ = [
    "Novedad",
    "NovedadesDesdeUltimaVisita",
    "VisitaMarcada",
    "corte_ultima_visita",
    "desde_ultima_visita",
]

#: Ventana máxima hacia atrás. Sin tope, la primera visita de alguien que
#: llevaba tres meses fuera traería tres meses de cambios y el diff dejaría de
#: ser un diff. Catorce días es lo que cabe leer de una sentada.
DIAS_MAXIMOS = 14


class Novedad(BaseModel):
    """Una línea del diff personal."""

    model_config = ConfigDict(extra="forbid")

    #: Uno de `SUBTIPOS` de `services/avisos.py`, o `pursuit` para el equipo.
    subtipo: str
    titulo: str
    detalle: str | None = None
    #: Expediente al que se refiere, para poder abrirlo.
    licitacion_id: str | None = None
    #: ISO. Ordena el diff.
    cuando: str


class NovedadesDesdeUltimaVisita(BaseModel):
    """El diff personal del Resumen."""

    model_config = ConfigDict(extra="forbid")

    #: Marca desde la que se calculó, para que la UI pueda decir «desde el
    #: jueves» en vez de «recientemente».
    desde: str
    items: list[Novedad] = Field(default_factory=list)
    #: Conteo por subtipo, para agrupar sin recontar.
    por_subtipo: dict[str, int] = Field(default_factory=dict)
    #: `True` cuando la ventana se recortó a `DIAS_MAXIMOS`: la UI lo dice, en
    #: vez de dar a entender que no pasó nada antes.
    ventana_recortada: bool = False


class VisitaMarcada(BaseModel):
    """Respuesta de «marcar todo como visto»: la nueva marca de última visita."""

    model_config = ConfigDict(extra="forbid")

    #: ISO-8601 UTC. La siguiente lectura de la banda calcula desde aquí.
    visto_en: str


#: Clave de orden de los ítems sin fecha legible: quedan por debajo de todos.
_SIN_INSTANTE = datetime.min.replace(tzinfo=UTC)


def _instante(cuando: str) -> datetime | None:
    """``cuando`` como instante UTC, o ``None`` si no se entiende.

    Las cuatro fuentes no escriben la fecha igual: el historial y el ledger
    llevan ISO con ``T``, los pliegos antiguos el ``now()::text`` de Postgres
    (con espacio y offset corto, ``2026-09-16 15:00:00+00``) y los recursos
    sólo la fecha. Comparadas como texto, ``' ' < 'T'`` dejaba un pliego de hoy
    por debajo de cualquier cambio de hoy aunque fuera posterior. Una fecha sin
    hora vale su medianoche UTC, que es como la comparaba el texto.
    """
    if not cuando:
        return None
    try:
        dt = datetime.fromisoformat(cuando.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _cuando_iso(cuando: Any) -> str:
    """``cuando`` en ISO-8601 UTC con ``T``, que es lo que el cliente sabe leer.

    El ``2026-09-16 15:00:00+00`` de un pliego antiguo no es un ``dateTime``
    válido para ``<time>`` y ``Date`` no lo lee en todos los navegadores. Una
    fecha sin hora se deja como está (decir «00:00» sería inventar la hora), y
    lo ilegible también: el orden ya lo manda al final.
    """
    texto = str(cuando or "")
    if len(texto) <= 10:
        return texto
    instante = _instante(texto)
    return instante.isoformat() if instante is not None else texto


def _a_novedad(aviso: Aviso, licitacion_id: str | None, cuando: Any) -> Novedad:
    return Novedad(
        subtipo=aviso.subtipo,
        titulo=aviso.titulo,
        detalle=aviso.detalle,
        licitacion_id=str(licitacion_id) if licitacion_id else None,
        cuando=_cuando_iso(cuando),
    )


def _snapshot(raw: Any) -> dict[str, Any]:
    """El estado anterior guardado en el historial, o ``{}`` si no se entiende."""
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _campos(raw: Any) -> list[str]:
    """``changed_fields`` viene como JSON o como CSV según la época."""
    texto = str(raw or "").strip()
    if not texto:
        return []
    if texto.startswith("["):
        try:
            parsed = json.loads(texto)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return [str(v) for v in parsed] if isinstance(parsed, list) else []
    return [p.strip() for p in texto.split(",") if p.strip()]


def corte_ultima_visita(last_seen: str | None) -> tuple[datetime, bool]:
    """Desde cuándo mira el Resumen, y si ese corte se recortó al tope.

    ``last_seen`` es la última visita (:func:`db.notifications.get_last_seen_ts`).
    Sin ella —primera visita, o un valor ilegible— el corte es el tope de
    :data:`DIAS_MAXIMOS`; con una anterior al tope, también, y entonces
    ``recortada`` es ``True``.

    Es función aparte porque el Resumen tiene dos bandas «desde tu última
    visita» —lo que sigues (:func:`desde_ultima_visita`) y las licitaciones
    nuevas del mercado (``/analytics/resumen/novedades``)— y las dos tienen que
    decir **la misma fecha**: con dos cortes distintos la pantalla afirmaba dos
    últimas visitas a la vez, y «Marcar todo como visto» solo movía una.
    """
    tope = datetime.now(UTC) - timedelta(days=DIAS_MAXIMOS)
    if not last_seen:
        return tope, False
    try:
        marcado = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
    except ValueError:
        log.warning("novedades_last_seen_invalido", valor=str(last_seen)[:40])
        return tope, False
    # En UTC siempre: el corte viaja al SQL como texto y se compara con
    # columnas escritas en UTC, así que una marca en `+02:00` cortaría en su
    # hora de pared y dejaría fuera las dos horas siguientes.
    marcado = marcado.replace(tzinfo=UTC) if marcado.tzinfo is None else marcado.astimezone(UTC)
    if marcado < tope:
        return tope, True
    return marcado, False


def desde_ultima_visita(
    user_key: str,
    *,
    last_seen: str | None,
    organization_id: int | None = None,
    limit: int = 40,
    user_id: int | None = None,
) -> NovedadesDesdeUltimaVisita:
    """El diff personal desde ``last_seen``.

    ``user_id`` (v129) hace dual la lectura de los favoritos: sin él, lo
    seguido bajo la clave de un correo anterior no generaría novedades.

    Sin ``last_seen`` —primera visita, o navegador nuevo— se usa la ventana
    máxima. No se devuelve vacío: alguien que entra por primera vez desde otro
    equipo también quiere ver qué pasó, y decirle «nada» sería falso.

    Cada fuente va en su propio ``try``: que el historial esté caído no puede
    esconder los documentos nuevos. Es la misma decisión que toman el Radar y
    la búsqueda global, por el mismo motivo.
    """
    desde, recortada = corte_ultima_visita(last_seen)
    desde_iso = desde.isoformat()
    items: list[Novedad] = []

    try:
        for fila in _repo.cambios_en_seguidos(
            user_key, desde_iso=desde_iso, limit=limit, user_id=user_id
        ):
            aviso = clasificar_cambio(
                _snapshot(fila.get("snapshot_json")),
                {
                    "estado": fila.get("estado"),
                    "fecha_limite": fila.get("fecha_limite"),
                    "importe": fila.get("importe"),
                },
                _campos(fila.get("changed_fields")),
            )
            items.append(_a_novedad(aviso, fila.get("id_externo"), fila.get("captured_at")))
    except Exception:
        log.warning("novedades_cambios_error", exc_info=True)

    try:
        for fila in _repo.documentos_nuevos_en_seguidos(
            user_key, desde_iso=desde_iso, limit=limit, user_id=user_id
        ):
            items.append(
                _a_novedad(
                    aviso_documento_nuevo(fila.get("tipo")),
                    fila.get("licitacion_id"),
                    fila.get("publicado_en"),
                )
            )
    except Exception:
        log.warning("novedades_documentos_error", exc_info=True)

    try:
        for fila in _repo.recursos_en_seguidos(user_key, desde_iso=desde_iso, user_id=user_id):
            items.append(
                _a_novedad(
                    aviso_recurso(fila.get("sentido")),
                    fila.get("licitacion_id"),
                    fila.get("fecha"),
                )
            )
    except Exception:
        log.warning("novedades_recursos_error", exc_info=True)

    if organization_id is not None:
        try:
            for fila in _repo.pursuits_movidos(organization_id, desde_iso=desde_iso):
                titulo = str(fila.get("titulo") or fila.get("licitacion_id") or "")
                items.append(
                    Novedad(
                        subtipo="pursuit",
                        titulo=f"Tu equipo movió «{titulo[:70]}»",
                        detalle=f"Ahora está en {fila.get('status')}.",
                        licitacion_id=str(fila.get("licitacion_id") or "") or None,
                        cuando=_cuando_iso(fila.get("created_at")),
                    )
                )
        except Exception:
            log.warning("novedades_pursuits_error", exc_info=True)

    # Orden por instante descendente, no por el texto (ver `_instante`). Las
    # que vienen sin fecha legible caen al final en vez de encabezar el diff.
    #
    # La clave empieza por «tiene instante» y no por «no lo tiene»: con
    # `reverse=True` la tupla entera se invierte, así que `(True, …)` para los
    # sin fecha los pondría **por encima** de cualquier fecha real.
    def _clave(n: Novedad) -> tuple[bool, datetime]:
        instante = _instante(n.cuando)
        return (instante is not None, instante or _SIN_INSTANTE)

    items.sort(key=_clave, reverse=True)
    items = items[:limit]

    por_subtipo: dict[str, int] = {}
    for item in items:
        por_subtipo[item.subtipo] = por_subtipo.get(item.subtipo, 0) + 1

    return NovedadesDesdeUltimaVisita(
        desde=desde_iso,
        items=items,
        por_subtipo=por_subtipo,
        ventana_recortada=recortada,
    )
