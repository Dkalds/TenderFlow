"""Productores del outbox que no nacen de una mutación: F1.5, F5.1 y F5.2.

Un documento nuevo en un expediente seguido lo trae la ingesta de pliegos, una
resolución de recurso la trae el scraper del TACRC, y un contrato entra solo en
su ventana de vencimiento. Ninguno es algo que un usuario *haga*, así que no
tienen un camino de escritura donde colgar el evento en la misma transacción.
Se derivan aquí, al principio de cada pasada del despachador
(``scheduler/jobs/event_dispatch.run``), igual que ``pursuit.task_due``.

Hasta aquí estos hechos sólo alimentaban el diff «desde tu última visita»
(``services/novedades.py``): quien no abría el Resumen no se enteraba de que
habían publicado el pliego técnico de lo que seguía.

Tres reglas comunes:

- **Cursor, no ventana.** Cada productor guarda en ``ingestion_cursors`` hasta
  dónde leyó (id de ``documentos``, id de ``resoluciones_recurso``,
  ``primera_extraccion`` de ``licitaciones``). Una pasada caída no pierde nada
  y una pasada repetida no duplica.
- **La primera pasada no mira atrás.** Sin cursor, se fija en el máximo actual
  y no se emite nada: encender esto no puede convertir el histórico entero en
  avisos (la misma decisión que la antigüedad máxima del despachador).
- **Los destinatarios viajan con ``user_id``** (ADR-030). La traducción a la
  clave de la bandeja la hace el despachador en su único punto de traducción.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from db.database import get_cursor, set_cursor
from db.events import append_domain_event, get_events, seguidores_de_licitacion
from db.repositories.cuentas import CuentasRepository
from db.repositories.novedades import AvisosSeguidosRepository
from observability.logging import get_logger
from services.avisos import aviso_documento_nuevo, aviso_recurso

log = get_logger(__name__)

__all__ = [
    "CURSOR_CUENTAS",
    "CURSOR_DOCUMENTOS",
    "CURSOR_RECURSOS",
    "ResumenAvisos",
    "emitir_avisos",
    "emitir_avisos_de_cuentas",
    "emitir_documentos_nuevos",
    "emitir_recursos",
    "emitir_vencimientos_de_cuentas",
]

CURSOR_DOCUMENTOS = "outbox_documentos_nuevos"
CURSOR_RECURSOS = "outbox_recursos"
CURSOR_CUENTAS = "outbox_cuentas_publicaciones"

#: Borde de la ventana de vencimiento de F1.5: «vence en seis meses».
DIAS_VENCIMIENTO = 183
#: Anchura de la franja que se examina bajo el borde. Siete días: un cierre
#: caído un fin de semana largo no se salta ningún contrato, y la idempotencia
#: por ``(cuenta, expediente, fecha_fin)`` impide repetir los que ya avisaron.
FRANJA_VENCIMIENTO_DIAS = 7

#: Techo de filas por productor y pasada. Si se llena, el cursor avanza sólo
#: hasta la última fila leída y el resto sale en la pasada siguiente.
LOTE_DOCUMENTOS = 500
LOTE_RECURSOS = 200
LOTE_PUBLICACIONES = 500

_avisos = AvisosSeguidosRepository()
_cuentas = CuentasRepository()


@dataclass
class ResumenAvisos:
    """Cuántos eventos escribió cada productor en la pasada."""

    documentos: int = 0
    recursos: int = 0
    publicaciones: int = 0
    vencimientos: int = 0

    @property
    def total(self) -> int:
        return self.documentos + self.recursos + self.publicaciones + self.vencimientos


# ── Seguidores ───────────────────────────────────────────────────────────────


def _seguidores(id_externo: str) -> list[dict[str, Any]]:
    """Quién sigue el expediente, listo para el payload.

    Pasa las filas de ``seguidores_de_licitacion`` tal cual (favoritos con su
    clave e id, oportunidades con el id del responsable): el despachador ya
    sabe resolver las dos formas. Se descartan las que no tienen organización,
    que no tendrían bandeja donde caer.
    """
    vistos: set[tuple[Any, ...]] = set()
    filas: list[dict[str, Any]] = []
    for fila in seguidores_de_licitacion(id_externo):
        if not fila.get("organization_id"):
            continue
        clave = tuple(sorted((k, str(v)) for k, v in fila.items()))
        if clave in vistos:
            continue
        vistos.add(clave)
        filas.append(dict(fila))
    return filas


def _organizaciones(seguidores: list[dict[str, Any]]) -> list[int]:
    return sorted({int(f["organization_id"]) for f in seguidores if f.get("organization_id")})


def _cursor_entero(fuente: str) -> int | None:
    cursor = get_cursor(fuente)
    if cursor is None or cursor.get("last_entry_id") in (None, ""):
        return None
    try:
        return int(str(cursor["last_entry_id"]))
    except ValueError:
        log.warning("avisos_outbox_cursor_ilegible", fuente=fuente)
        return None


# ── F5.1: documentos nuevos ──────────────────────────────────────────────────


def emitir_documentos_nuevos() -> int:
    """Un ``licitacion.documento_nuevo`` por adjunto nuevo de un expediente seguido.

    La identidad del adjunto es su ``source_hash`` (v88), que la consulta ya
    aplica: el mismo pliego con el token de la URL rotado no vuelve a avisar.

    Un evento por **organización** que sigue el expediente, con sus
    seguidores: así el webhook de cada organización lo recibe una vez y sólo
    ve a los suyos.
    """
    hasta = _avisos.max_documento_id()
    desde = _cursor_entero(CURSOR_DOCUMENTOS)
    if desde is None:
        set_cursor(CURSOR_DOCUMENTOS, last_entry_id=str(hasta))
        log.info("avisos_outbox_cursor_inicializado", fuente=CURSOR_DOCUMENTOS, hasta=hasta)
        return 0
    if hasta <= desde:
        return 0

    filas = _avisos.documentos_nuevos_seguidos(
        desde_id=desde, hasta_id=hasta, limit=LOTE_DOCUMENTOS
    )
    emitidos = 0
    for fila in filas:
        id_externo = str(fila["licitacion_id"])
        aviso = aviso_documento_nuevo(fila.get("tipo"))
        seguidores = _seguidores(id_externo)
        for organization_id in _organizaciones(seguidores):
            append_domain_event(
                "licitacion.documento_nuevo",
                id_externo,
                "licitacion",
                {
                    "id_externo": id_externo,
                    "licitacion_id": id_externo,
                    "titulo": fila.get("titulo"),
                    "documento_id": int(fila["documento_id"]),
                    "tipo": fila.get("tipo"),
                    "filename": fila.get("filename"),
                    "subtipo": aviso.subtipo,
                    "aviso_titulo": aviso.titulo,
                    "aviso_detalle": aviso.detalle,
                    "organization_id": organization_id,
                    "seguidores": [
                        f for f in seguidores if int(f["organization_id"]) == organization_id
                    ],
                },
                organization_id=organization_id,
            )
            emitidos += 1
    # Si el lote se llenó, el cursor avanza sólo hasta la última fila leída y
    # el resto sale en la pasada siguiente; si no, hasta el tope fijado arriba.
    nuevo = int(filas[-1]["documento_id"]) if len(filas) >= LOTE_DOCUMENTOS else hasta
    set_cursor(CURSOR_DOCUMENTOS, last_entry_id=str(nuevo))
    return emitidos


# ── F5.2: recursos ───────────────────────────────────────────────────────────


def emitir_recursos() -> int:
    """Un ``licitacion.recurso`` por resolución nueva sobre un expediente seguido.

    El ``sentido`` (estimado, desestimado, inadmitido) va en el titular porque
    decide la reacción: un recurso estimado puede reabrir el plazo.
    """
    hasta = _avisos.max_resolucion_id()
    desde = _cursor_entero(CURSOR_RECURSOS)
    if desde is None:
        set_cursor(CURSOR_RECURSOS, last_entry_id=str(hasta))
        log.info("avisos_outbox_cursor_inicializado", fuente=CURSOR_RECURSOS, hasta=hasta)
        return 0
    if hasta <= desde:
        return 0

    filas = _avisos.recursos_seguidos(desde_id=desde, hasta_id=hasta, limit=LOTE_RECURSOS)
    emitidos = 0
    for fila in filas:
        id_externo = str(fila["licitacion_id"])
        sentido = fila.get("sentido")
        aviso = aviso_recurso(sentido)
        seguidores = _seguidores(id_externo)
        for organization_id in _organizaciones(seguidores):
            append_domain_event(
                "licitacion.recurso",
                id_externo,
                "licitacion",
                {
                    "id_externo": id_externo,
                    "licitacion_id": id_externo,
                    "titulo": fila.get("titulo"),
                    "resolucion_id": int(fila["resolucion_id"]),
                    "sentido": sentido,
                    "tribunal": fila.get("tribunal"),
                    "numero_resolucion": fila.get("numero_resolucion"),
                    "fecha": fila.get("fecha"),
                    "subtipo": aviso.subtipo,
                    "aviso_titulo": aviso.titulo,
                    "aviso_detalle": aviso.detalle,
                    "organization_id": organization_id,
                    "seguidores": [
                        f for f in seguidores if int(f["organization_id"]) == organization_id
                    ],
                },
                organization_id=organization_id,
            )
            emitidos += 1
    nuevo = int(filas[-1]["resolucion_id"]) if len(filas) >= LOTE_RECURSOS else hasta
    set_cursor(CURSOR_RECURSOS, last_entry_id=str(nuevo))
    return emitidos


# ── F1.5: cuentas objetivo ───────────────────────────────────────────────────


def _miembros(organization_id: int, cache: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Los miembros activos como seguidores. Una consulta por organización."""
    if organization_id not in cache:
        cache[organization_id] = [
            {"user_id": user_id, "organization_id": organization_id}
            for user_id in _cuentas.miembros_activos(organization_id)
        ]
    return cache[organization_id]


def emitir_avisos_de_cuentas(ahora: datetime | None = None) -> int:
    """Un ``cuenta.publicacion_nueva`` por expediente nuevo de un órgano seguido.

    Uno por (organización, expediente): dos organizaciones que siguen el mismo
    órgano reciben cada una el suyo, y los destinatarios son los miembros
    activos de cada una —seguir una cuenta es una decisión de equipo—.
    """
    marca = (ahora or datetime.now(UTC)).isoformat()
    cursor = get_cursor(CURSOR_CUENTAS)
    desde = (cursor or {}).get("last_seen_updated")
    if not desde:
        set_cursor(CURSOR_CUENTAS, last_seen_updated=marca)
        log.info("avisos_outbox_cursor_inicializado", fuente=CURSOR_CUENTAS, hasta=marca)
        return 0

    filas = _cuentas.publicaciones_nuevas(
        desde_iso=str(desde), hasta_iso=marca, limit=LOTE_PUBLICACIONES
    )
    miembros: dict[int, list[dict[str, Any]]] = {}
    emitidos = 0
    for fila in filas:
        organization_id = int(fila["organization_id"])
        id_externo = str(fila["id_externo"])
        organo = str(fila.get("organo_nombre") or "")
        append_domain_event(
            "cuenta.publicacion_nueva",
            id_externo,
            "licitacion",
            {
                "id_externo": id_externo,
                "licitacion_id": id_externo,
                "titulo": fila.get("titulo"),
                "organo": organo,
                "cuenta_id": int(fila["cuenta_id"]),
                "importe": fila.get("importe"),
                "fecha_limite": fila.get("fecha_limite"),
                "aviso_titulo": f"Publicación nueva de {organo}" if organo else None,
                "organization_id": organization_id,
                "seguidores": _miembros(organization_id, miembros),
            },
            organization_id=organization_id,
        )
        emitidos += 1
    nuevo = str(filas[-1]["primera_extraccion"]) if len(filas) >= LOTE_PUBLICACIONES else marca
    set_cursor(CURSOR_CUENTAS, last_seen_updated=nuevo)
    return emitidos


def emitir_vencimientos_de_cuentas() -> int:
    """Un ``cuenta.vencimiento_proximo`` cuando un contrato de una cuenta entra
    en los seis meses previos a su fin.

    Idempotente por ``(cuenta, expediente, fecha_fin)``: si la fecha de fin
    cambia (una prórroga), el contrato vuelve a entrar en la ventana otro día y
    eso sí es otro aviso.
    """
    filas = _cuentas.vencimientos_entrando(
        dias_desde=DIAS_VENCIMIENTO - FRANJA_VENCIMIENTO_DIAS, dias_hasta=DIAS_VENCIMIENTO
    )
    miembros: dict[int, list[dict[str, Any]]] = {}
    emitidos = 0
    for fila in filas:
        fecha_fin = str(fila.get("fecha_fin") or "")
        if not fecha_fin:
            continue
        organization_id = int(fila["organization_id"])
        cuenta_id = int(fila["cuenta_id"])
        id_externo = str(fila["id_externo"])
        agregado = f"{cuenta_id}:{id_externo}"
        previos = get_events("cuenta", agregado, event_type="cuenta.vencimiento_proximo")
        if any((ev.get("payload") or {}).get("fecha_fin") == fecha_fin for ev in previos):
            continue
        organo = str(fila.get("organo_nombre") or "")
        append_domain_event(
            "cuenta.vencimiento_proximo",
            agregado,
            "cuenta",
            {
                "id_externo": id_externo,
                "licitacion_id": id_externo,
                "titulo": fila.get("titulo"),
                "organo": organo,
                "cuenta_id": cuenta_id,
                "fecha_fin": fecha_fin,
                "aviso_titulo": f"Vence en seis meses un contrato de {organo}" if organo else None,
                "aviso_detalle": f"Fin previsto el {fecha_fin}.",
                "organization_id": organization_id,
                "seguidores": _miembros(organization_id, miembros),
            },
            organization_id=organization_id,
        )
        emitidos += 1
    return emitidos


# ── Pasada ───────────────────────────────────────────────────────────────────


def emitir_avisos() -> ResumenAvisos:
    """Corre los cuatro productores, cada uno aislado de los demás.

    Un fallo en uno (la tabla de recursos sin migrar, una consulta que tarda
    demasiado) no puede dejar sin avisos de documentos ni, sobre todo, impedir
    que el despachador reparta la cola: por eso cada uno va en su ``try`` y el
    fallo queda en el log con su nombre.
    """
    resumen = ResumenAvisos()
    for nombre, productor in (
        ("documentos", emitir_documentos_nuevos),
        ("recursos", emitir_recursos),
        ("publicaciones", emitir_avisos_de_cuentas),
        ("vencimientos", emitir_vencimientos_de_cuentas),
    ):
        try:
            setattr(resumen, nombre, int(productor()))
        except Exception:
            log.warning("avisos_outbox_productor_failed", productor=nombre, exc_info=True)
    if resumen.total:
        log.info(
            "avisos_outbox_emitidos",
            documentos=resumen.documentos,
            recursos=resumen.recursos,
            publicaciones=resumen.publicaciones,
            vencimientos=resumen.vencimientos,
        )
    return resumen
