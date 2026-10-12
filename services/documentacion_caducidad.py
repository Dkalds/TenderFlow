"""Caducidad de la documentación acreditativa de una organización.

``OrganizationCertification.vigente_hasta`` lo usaba solo el go/no-go, y solo
para decir «no cumple» cuando ya era tarde: nadie avisaba antes de que un
certificado caducara. Lo que deja fuera de una licitación no suele ser una ISO
caducada sino el papeleo —estar al corriente con la AEAT o con la Seguridad
Social, la inscripción en el ROLECE, la clasificación—, que caduca más a menudo
y se renueva en días si alguien se acuerda a tiempo.

Este módulo tiene dos mitades:

- **El juicio, puro**: estado de vigencia, umbral de aviso cruzado y texto del
  aviso. Sin BD, para que la pestaña Organización y el aviso no puedan
  discrepar sobre si un documento está a punto de caducar.
- **El productor**: :func:`emitir_avisos_de_caducidad` escribe en el outbox
  un ``organizacion.documento_caduca`` por documento y umbral, que el
  despachador entrega en la campana y por correo a owner y admin. Lo llama el
  paso ``documentacion_avisos`` del cierre de la pasada (ADR-012).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Final

from observability.logging import get_logger
from shared.dto import (
    EstadoVigencia,
    OrganizationCertification,
    OrganizationDocumentCategory,
    VigenciaDocumento,
)

log = get_logger(__name__)

#: Días antes de caducar en los que se avisa, y ``0`` para «ha caducado».
#:
#: Los 60 días dan margen a lo que se renueva con auditoría o tramitación (una
#: certificación, la clasificación); los avisos de 30 y 7 días recuerdan lo que
#: se renueva en días (los certificados de estar al corriente).
UMBRALES_DIAS: Final[tuple[int, ...]] = (60, 30, 7, 0)

#: Hasta dónde mira el barrido: el primer umbral.
HORIZONTE_DIAS: Final[int] = UMBRALES_DIAS[0]

EVENTO: Final[str] = "organizacion.documento_caduca"

#: Agregado de los eventos: un documento **con su vigencia**. Renovarlo con otra
#: fecha es otro agregado y vuelve a avisar en sus umbrales.
AGREGADO: Final[str] = "documento_organizacion"

_ROLES_QUE_RENUEVAN: Final[frozenset[str]] = frozenset({"owner", "admin"})


def categoria_de(tipo: str) -> OrganizationDocumentCategory:
    """``tecnica`` para las certificaciones; ``administrativa`` para el resto."""
    return "tecnica" if tipo == "certificacion_tecnica" else "administrativa"


def clave_documento(tipo: str, nombre: str) -> str:
    """Identidad estable de un documento dentro de su organización.

    El ``PUT`` del perfil reemplaza todas las filas, así que el ``id`` de la fila
    cambia cada vez que alguien guarda: no sirve para recordar qué se avisó. La
    identidad es el tipo y el nombre, sin mayúsculas ni espacios de más.
    """
    return f"{tipo}|{' '.join(nombre.casefold().split())}"


def dias_hasta(vigente_hasta: date, hoy: date) -> int:
    """Días que le quedan. ``0`` es su último día de vigencia; negativo, caducado."""
    return (vigente_hasta - hoy).days


def estado_de(vigente_hasta: date | None, hoy: date) -> tuple[EstadoVigencia, int | None]:
    """Estado de vigencia y días restantes, con el mismo corte que el go/no-go.

    Un documento vale hasta su ``vigente_hasta`` incluido: caduca el día
    siguiente (``services/go_no_go`` dice «no cumple» con ``vigente_hasta <
    hoy``).
    """
    if vigente_hasta is None:
        return "sin_caducidad", None
    dias = dias_hasta(vigente_hasta, hoy)
    if dias < 0:
        return "caducado", dias
    if dias <= HORIZONTE_DIAS:
        return "caduca_pronto", dias
    return "vigente", dias


def umbral_cruzado(vigente_hasta: date | None, hoy: date) -> int | None:
    """El umbral de aviso más próximo que ya se cruzó, o ``None``.

    Solo el más próximo: si el paso no corrió durante semanas y un documento
    pasó de 70 a 20 días, se avisa de los 30, no de los 60 y los 30 a la vez.
    """
    if vigente_hasta is None:
        return None
    dias = dias_hasta(vigente_hasta, hoy)
    if dias < 0:
        return 0
    cruzados = [umbral for umbral in UMBRALES_DIAS if umbral > 0 and dias <= umbral]
    return min(cruzados) if cruzados else None


def texto_aviso(nombre: str, vigente_hasta: date, dias: int) -> tuple[str, str]:
    """``(encabezado, detalle)`` del aviso, con los días reales que quedan."""
    fecha = vigente_hasta.isoformat()
    if dias < 0:
        return (
            "Ha caducado",
            f"«{nombre}» caducó el {fecha}. Renuévalo antes de presentarte a una "
            "licitación que lo exija.",
        )
    if dias == 0:
        encabezado = "Caduca hoy"
    elif dias == 1:
        encabezado = "Caduca mañana"
    else:
        encabezado = f"Caduca en {dias} días"
    return encabezado, f"«{nombre}» vale hasta el {fecha}. Pide la renovación a tiempo."


def vigencias(
    documentos: Iterable[OrganizationCertification], hoy: date
) -> list[VigenciaDocumento]:
    """Vigencia de cada documento, ordenada por la próxima caducidad.

    Lo caducado sale primero —su fecha es la más antigua—, después por fecha, y
    lo que no declara caducidad al final: no tiene fecha con la que competir.
    """
    filas: list[VigenciaDocumento] = []
    for documento in documentos:
        estado, dias = estado_de(documento.vigente_hasta, hoy)
        filas.append(
            VigenciaDocumento(
                nombre=documento.nombre,
                tipo=documento.tipo,
                categoria=categoria_de(documento.tipo),
                vigente_hasta=documento.vigente_hasta,
                estado=estado,
                dias_restantes=dias,
            )
        )
    return sorted(
        filas,
        key=lambda f: (f.vigente_hasta is None, f.vigente_hasta or date.max, f.nombre.casefold()),
    )


# ── Productor del outbox ─────────────────────────────────────────────────────


def _documento_id(organization_id: int, clave: str, vigente_hasta: date) -> str:
    """Identificador corto y estable de un documento con su vigencia.

    Viaja en el payload (lo leen el despachador y los webhooks) y no el nombre
    tal cual: es más corto como discriminante de la notificación y no cambia de
    forma si alguien escribe el nombre con otras mayúsculas.
    """
    crudo = f"{organization_id}|{clave}|{vigente_hasta.isoformat()}"
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:16]


def _a_fecha(valor: Any) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str) and valor:
        return date.fromisoformat(valor[:10])
    return None


def _quienes_renuevan(organization_id: int, cache: dict[int, list[int]]) -> list[int]:
    """Owner y admin activos: quienes pueden cambiar el perfil y renovar."""
    if organization_id not in cache:
        from db.repositories.organizations import OrganizationRepository

        cache[organization_id] = sorted(
            int(miembro["user_id"])
            for miembro in OrganizationRepository().list_members(organization_id)
            if miembro.get("status") == "active" and miembro.get("role") in _ROLES_QUE_RENUEVAN
        )
    return cache[organization_id]


def emitir_avisos_de_caducidad(hoy: date | None = None) -> int:
    """Escribe un ``organizacion.documento_caduca`` por documento y umbral cruzado.

    Devuelve cuántos eventos escribió. **Una vez por umbral y documento**: el
    paso corre a diario y cada pasada vería los mismos documentos, así que antes
    de escribir se mira si ese documento, con esa vigencia, ya avisó de ese
    umbral. Renovarlo con otra fecha es otro agregado y vuelve a avisar.

    Un documento sin nadie que pueda renovarlo (organización sin owner ni admin
    activos) no escribe evento: no habría destinatario y la fila solo
    engordaría la cola.
    """
    from datetime import timedelta

    from db.events import append_domain_event, get_events
    from db.repositories.organization_capabilities import OrganizationCapabilitiesRepository

    dia = hoy or datetime.now(UTC).date()
    destinatarios: dict[int, list[int]] = {}
    emitidos = 0
    for fila in OrganizationCapabilitiesRepository().documentos_que_caducan_hasta(
        dia + timedelta(days=HORIZONTE_DIAS)
    ):
        vigente_hasta = _a_fecha(fila.get("vigente_hasta"))
        umbral = umbral_cruzado(vigente_hasta, dia)
        if vigente_hasta is None or umbral is None:
            continue
        organization_id = int(fila["organization_id"])
        nombre = str(fila["nombre"])
        tipo = str(fila.get("tipo") or "certificacion_tecnica")
        clave = clave_documento(tipo, nombre)
        documento_id = _documento_id(organization_id, clave, vigente_hasta)
        agregado = f"{organization_id}|{documento_id}"
        if any(
            (previo.get("payload") or {}).get("umbral") == umbral
            for previo in get_events(AGREGADO, agregado, event_type=EVENTO)
        ):
            continue
        seguidores = _quienes_renuevan(organization_id, destinatarios)
        if not seguidores:
            log.info("documentacion_aviso_sin_destinatario", organization_id=organization_id)
            continue
        dias = dias_hasta(vigente_hasta, dia)
        encabezado, detalle = texto_aviso(nombre, vigente_hasta, dias)
        append_domain_event(
            EVENTO,
            agregado,
            AGREGADO,
            {
                "organization_id": organization_id,
                "documento_id": documento_id,
                "documento": nombre,
                "tipo": tipo,
                "categoria": categoria_de(tipo),
                "vigente_hasta": vigente_hasta.isoformat(),
                "umbral": umbral,
                "dias_restantes": dias,
                # `titulo`, `aviso_titulo` y `aviso_detalle` son lo que pintan
                # la campana (`event_dispatch._titulo_y_cuerpo`) y el digest
                # (`email_digest.bloques_de_avisos`).
                "titulo": nombre,
                "aviso_titulo": encabezado,
                "aviso_detalle": detalle,
                "seguidores": [
                    {"user_id": user_id, "organization_id": organization_id}
                    for user_id in seguidores
                ],
            },
            organization_id=organization_id,
        )
        emitidos += 1
    return emitidos
