"""Envío de los informes programados (T6).

Qué hace en una pasada
----------------------
1. Pide a ``db.repositories.report_schedules.pendientes`` las programaciones
   cuya ventana está abierta y **sin enviar** (la idempotencia vive en el SQL;
   ver su docstring).
2. Construye el informe de cada organización con ``services.informes``.
3. Si sale vacío, no manda nada, lo deja en ``ops_events`` y **sella la
   ventana igual** — o lo recalcularía en cada pasada durante toda la semana.
4. Resuelve los destinatarios, descuenta a quien se dio de baja, y envía el
   correo con el PDF adjunto.

Por qué un paso de la pipeline y no un cron propio
--------------------------------------------------
Porque es exactamente lo que ADR-012 nombra: un trabajo periódico más, que ya
tiene dos planos capaces de ejecutarlo (Actions hoy, el worker tras el cutover
de ADR-033). Un cron propio sería un tercer plano, que es la situación que
ADR-012 vino a terminar.

Consecuencia que hay que conocer: la pipeline corre **cada cuatro horas**, así
que un informe programado a las 07:00 sale en la primera pasada posterior a esa
hora, no a las 07:00 en punto. Es aceptable para un informe semanal y es la
razón de que la ventana sea de un día entero y no de una hora.

Contrato de fallo
-----------------
Como el resto de jobs advisory: **no lanza**. Un ESP caído, una organización
sin miembros o un PDF que no se pudo maquetar afectan a **esa** organización;
que tumben la pasada entera sería cambiar un informe no enviado por una
ingesta no ejecutada.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

#: Tipo de aviso sobre el que el usuario expresa el opt-out. Vive en
#: `notification_preferences` (canal `email`), que es donde el usuario ya tiene
#: el resto de sus interruptores: un segundo sitio para decir «esto no» es un
#: sitio donde alguien lo dirá sin efecto.
TIPO_AVISO = "informe_semanal"

#: Roles que reciben el informe cuando no hay lista explícita. Los mismos que
#: pueden abrir Dirección (`services.direccion.ROLES_DIRECCION`): el informe es
#: esa pantalla en un correo, y mandarlo a quien no puede abrirla sería
#: enseñarle por correo lo que la aplicación le oculta.
ROLES_POR_DEFECTO: frozenset[str] = frozenset({"owner", "admin"})


@dataclass(slots=True)
class Resumen:
    """Qué hizo la pasada. Lo devuelve el job y lo registra el paso."""

    programadas: int = 0
    enviados: int = 0
    vacios: int = 0
    sin_destinatarios: int = 0
    fallidos: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _destinatarios(fila: dict[str, Any]) -> list[tuple[int | None, str]]:
    """``(user_id, email)`` de quien debe recibirlo, ya filtrado por opt-out.

    Con lista explícita el ``user_id`` es ``None``: son correos que alguien
    escribió y que pueden no corresponder a ninguna cuenta —una lista de
    distribución, el buzón de dirección—. Esos no tienen preferencia que
    consultar, y darse de baja de ellos es quitarlos de la lista.
    """
    from db.repositories import notification_preferences as prefs
    from db.repositories.organizations import OrganizationRepository

    organization_id = int(fila["organization_id"])
    explicitos = fila.get("destinatarios") or []
    if explicitos:
        return [(None, str(correo).strip()) for correo in explicitos if str(correo).strip()]

    salida: list[tuple[int | None, str]] = []
    for miembro in OrganizationRepository().list_members(organization_id):
        if str(miembro.get("role") or "") not in ROLES_POR_DEFECTO:
            continue
        if str(miembro.get("status") or "active") != "active":
            continue
        correo = str(miembro.get("email") or "").strip()
        if not correo:
            continue
        user_id = int(miembro["user_id"])
        try:
            frecuencia = prefs.resolver(
                user_id, tipo=TIPO_AVISO, canal="email", organization_id=organization_id
            )
        except Exception:
            # Sin preferencia legible se envía: el informe es una función que
            # el owner activó a propósito, y silenciarlo por un fallo de
            # lectura sería decidir por él en la dirección menos recuperable.
            log.warning("informe_prefs_ilegibles", user_id=user_id, exc_info=True)
            frecuencia = "daily"
        if frecuencia == "off":
            continue
        salida.append((user_id, correo))
    return salida


def _enviar(fila: dict[str, Any], informe: Any, destinos: list[tuple[int | None, str]]) -> int:
    """Manda el informe a cada destinatario. Devuelve cuántos salieron."""
    from observability.mailer import Adjunto, Mensaje, enviar
    from services.app_urls import frontend_base_url
    from services.email_digest import url_de_baja_de_tipo
    from services.informes import nombre_pdf, render_html, render_pdf

    try:
        pdf = render_pdf(informe)
        adjuntos = [Adjunto(nombre_pdf(informe), pdf, "application/pdf")]
    except Exception:
        # Sin PDF el correo sigue teniendo las mismas tablas en HTML. Perder el
        # adjunto es peor que perder el informe entero, pero mucho menos.
        log.warning("informe_pdf_fallido", organization_id=fila["organization_id"], exc_info=True)
        adjuntos = []

    # `frontend_base_url()` y no `settings.FRONTEND_URL`: esa variable existe en
    # `render.yaml` pero **no** está declarada en `config/settings.py`, así que
    # un `getattr` sobre ella siempre daba "" y el enlace de baja nunca se
    # construía —el correo salía sin `List-Unsubscribe`, justo lo contrario de
    # lo que promete `docs/informes-programados.md`—. Lo cazó el guard
    # `test_unit_settings_getattr_guard`. El helper deduce el origen de
    # `CORS_ALLOWED_ORIGINS`, que es lo que hacen los digests de watchlist.
    base = frontend_base_url() or ""
    enviados = 0
    for user_id, correo in destinos:
        # `url_de_baja_de_tipo` y no la del digest: aquella pausa **todas** las
        # reglas de watchlist y no toca este informe. Salió apuntando ahí, así
        # que pulsar «dejar de recibir este informe» —o el POST automático que
        # hace Gmail por RFC 8058— borraba las alertas de licitaciones de esa
        # persona y el informe seguía llegando. Ésta apaga `informe_semanal`
        # en el canal `email`, que es donde `_destinatarios` mira.
        url_baja = url_de_baja_de_tipo(user_id, TIPO_AVISO, base)
        resultado = enviar(
            Mensaje(
                to=correo,
                subject=informe.asunto,
                html=render_html(informe, url_baja=url_baja),
                tags=["informe-semanal"],
                unsubscribe_url=url_baja,
                adjuntos=adjuntos,
            )
        )
        if resultado.ok:
            enviados += 1
        else:
            log.warning(
                "informe_envio_fallido",
                organization_id=fila["organization_id"],
                motivo=resultado.motivo,
                error=resultado.error,
            )
    return enviados


def ejecutar(ahora: datetime | None = None) -> Resumen:
    """Una pasada completa. **No lanza**: ver la cabecera."""
    from db.repositories import report_schedules
    from db.repositories.organizations import OrganizationRepository
    from observability.ops_events import record_event
    from services.informes import construir

    instante = (ahora or datetime.now(UTC)).astimezone(UTC)
    resumen = Resumen()
    try:
        filas = report_schedules.pendientes(instante)
    except Exception:
        log.warning("informes_programados_lectura_fallida", exc_info=True)
        return resumen

    resumen.programadas = len(filas)
    organizaciones = OrganizationRepository()
    for fila in filas:
        organization_id = int(fila["organization_id"])
        try:
            org = organizaciones.get_by_id(organization_id) or {}
            informe = construir(
                organization_id, organizacion=str(org.get("name") or ""), ahora=instante
            )

            if informe.vacio:
                resumen.vacios += 1
                # En `ops_events` y no sólo en el log: «esta semana no salió
                # informe» es una pregunta que se le hace a la operación, y el
                # log rota.
                record_event(
                    "informe_semanal_vacio",
                    detail=f"organization_id={organization_id}",
                )
                report_schedules.marcar_envio(int(fila["id"]), estado="vacio", instante=instante)
                continue

            destinos = _destinatarios(fila)
            if not destinos:
                resumen.sin_destinatarios += 1
                record_event(
                    "informe_semanal_sin_destinatarios",
                    detail=f"organization_id={organization_id}",
                )
                report_schedules.marcar_envio(
                    int(fila["id"]), estado="sin_destinatarios", instante=instante
                )
                continue

            enviados = _enviar(fila, informe, destinos)
            resumen.enviados += enviados
            if not enviados:
                # Constancia **sin** sellar la ventana, que son dos cosas
                # distintas. El mailer no lanza ante un fallo del ESP: devuelve
                # `ResultadoEnvio(ok=False)`, así que una caída del proveedor
                # llegaba a `marcar_envio` y estampaba `ultimo_envio_at`; con
                # eso `pendientes()` dejaba de devolver la fila y la
                # organización se quedaba sin informe la semana entera. Pero
                # limitarse a no sellar dejaba `ultimo_estado` con el
                # `enviado:3/3` de la semana pasada, diciéndole a quien mira
                # que el correo salió. Así la pasada siguiente reintenta y el
                # diagnóstico dice la verdad.
                resumen.fallidos += 1
                report_schedules.marcar_estado(int(fila["id"]), estado="fallido")
                record_event(
                    "informe_semanal_fallido",
                    detail=f"organization_id={organization_id}",
                )
                log.warning(
                    "informe_no_salio_ninguno",
                    organization_id=organization_id,
                    destinos=len(destinos),
                )
                continue
            report_schedules.marcar_envio(
                int(fila["id"]),
                estado=f"enviado:{enviados}/{len(destinos)}",
                instante=instante,
            )
        except Exception:
            resumen.fallidos += 1
            log.warning("informe_semanal_fallido", organization_id=organization_id, exc_info=True)

    log.info("informes_programados_done", **resumen.as_dict())
    return resumen


def run() -> dict[str, int]:
    """Punto de entrada del registry y del paso canónico."""
    return ejecutar().as_dict()
