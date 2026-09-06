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

__all__ = ["Novedad", "NovedadesDesdeUltimaVisita", "desde_ultima_visita"]

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


def _a_novedad(aviso: Aviso, licitacion_id: str | None, cuando: Any) -> Novedad:
    return Novedad(
        subtipo=aviso.subtipo,
        titulo=aviso.titulo,
        detalle=aviso.detalle,
        licitacion_id=str(licitacion_id) if licitacion_id else None,
        cuando=str(cuando or ""),
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


def desde_ultima_visita(
    user_key: str,
    *,
    last_seen: str | None,
    organization_id: int | None = None,
    limit: int = 40,
) -> NovedadesDesdeUltimaVisita:
    """El diff personal desde ``last_seen``.

    Sin ``last_seen`` —primera visita, o navegador nuevo— se usa la ventana
    máxima. No se devuelve vacío: alguien que entra por primera vez desde otro
    equipo también quiere ver qué pasó, y decirle «nada» sería falso.

    Cada fuente va en su propio ``try``: que el historial esté caído no puede
    esconder los documentos nuevos. Es la misma decisión que toman el Radar y
    la búsqueda global, por el mismo motivo.
    """
    tope = datetime.now(UTC) - timedelta(days=DIAS_MAXIMOS)
    desde = tope
    recortada = False
    if last_seen:
        try:
            marcado = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
            if marcado.tzinfo is None:
                marcado = marcado.replace(tzinfo=UTC)
            if marcado < tope:
                recortada = True
            else:
                desde = marcado
        except ValueError:
            log.warning("novedades_last_seen_invalido", valor=str(last_seen)[:40])

    desde_iso = desde.isoformat()
    items: list[Novedad] = []

    try:
        for fila in _repo.cambios_en_seguidos(user_key, desde_iso=desde_iso, limit=limit):
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
        for fila in _repo.documentos_nuevos_en_seguidos(user_key, desde_iso=desde_iso, limit=limit):
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
        for fila in _repo.recursos_en_seguidos(user_key, desde_iso=desde_iso):
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
                        cuando=str(fila.get("created_at") or ""),
                    )
                )
        except Exception:
            log.warning("novedades_pursuits_error", exc_info=True)

    # Orden por fecha descendente. Las cuatro fuentes traen ISO, así que el
    # orden lexicográfico es el cronológico; las que vienen sin fecha caen al
    # final en vez de encabezar el diff por ordenar la cadena vacía primero.
    items.sort(key=lambda n: (n.cuando == "", n.cuando), reverse=True)
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
