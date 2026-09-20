"""Correo de digest de las reglas de watchlist: texto plano y HTML.

Hasta 2026-09 el digest salía por :func:`observability.alerts.notify`, es
decir, con la plantilla de **alerta de operación**: asunto ``[TenderFlow]
[INFO] Watchlist (daily): 3 licitación(es)``, franja de color de severidad y
pie de «alerta automática». Era el único contacto diario del producto con la
persona y parecía un aviso de monitorización. Este módulo escribe el correo
como lo que es —el resumen de la mañana— y sin motor de plantillas, igual que
el correo de acceso concedido: el proyecto no tiene Jinja y añadir una
dependencia para dos correos no compensa.

Funciones puras: reciben los datos ya cargados y devuelven cadenas. Así se
prueban sin SMTP ni base de datos.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

_MAX_POR_BLOQUE = 10
_ETIQUETA_FRECUENCIA = {
    "immediate": "nuevas ahora",
    "daily": "de hoy",
    "weekly": "de la semana",
}


@dataclass(frozen=True)
class BloqueDigest:
    """Las coincidencias de una regla (o entrada legada) de la watchlist, o
    los avisos de un mismo subtipo (F5.3) cuando ``es_aviso``."""

    etiqueta: str
    licitaciones: list[dict[str, Any]] = field(default_factory=list)
    #: El bloque agrupa avisos sobre lo que el usuario sigue («Plazo ampliado»,
    #: «Documento nuevo»), no licitaciones nuevas de una regla. Cambia la
    #: cabecera del correo: contar un plazo ampliado como «licitación nueva»
    #: sería mentir en la primera línea.
    es_aviso: bool = False


def _payload(crudo: Any) -> dict[str, Any]:
    if isinstance(crudo, dict):
        return crudo
    try:
        valor = json.loads(str(crudo or "{}"))
    except (TypeError, ValueError):
        return {}
    return valor if isinstance(valor, dict) else {}


def clave_de_aviso(evento_tipo: str | None, payload: dict[str, Any]) -> tuple[str, str]:
    """``(clave, etiqueta)`` del bloque del digest donde cae un aviso.

    Con ``subtipo`` (F5.3: los de ``licitacion.*``) se agrupa por él y se
    rotula con el nombre del catálogo de avisos. Sin él —una asignación, un
    comentario— el bloque es el tipo de evento con su título del catálogo, en
    vez del «tu regla» que salía cuando el digest sólo sabía de reglas.
    """
    from services.avisos import SUBTIPOS, etiqueta_de
    from shared.events import CATALOGO

    subtipo = str(payload.get("subtipo") or "")
    if subtipo in SUBTIPOS:
        return subtipo, etiqueta_de(subtipo)
    tipo = str(evento_tipo or "")
    spec = CATALOGO.get(tipo)
    return tipo or "evento", spec.titulo if spec else "Aviso"


def bloques_de_avisos(filas: list[dict[str, Any]]) -> list[BloqueDigest]:
    """Agrupa por subtipo las filas del digest que vienen de eventos (F5.3).

    ``filas`` son las de ``load_pending_digests`` con ``evento_tipo``. El
    orden de los bloques es el de ``SUBTIPOS`` —primero lo terminal: anulado,
    desierto, adjudicado…— y después los eventos sin subtipo, por nombre. Cada
    licitación del bloque lleva ``aviso``, el titular concreto («Plazo ampliado
    al 12/10»), que es lo que ``render_digest`` pinta bajo el título.
    """
    from services.avisos import SUBTIPOS

    grupos: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    for fila in filas:
        payload = _payload(fila.get("evento_payload"))
        clave, etiqueta = clave_de_aviso(fila.get("evento_tipo"), payload)
        licitacion = {
            "id_externo": fila.get("licitacion_id"),
            "titulo": fila.get("titulo") or payload.get("titulo") or fila.get("licitacion_id"),
            "organo_contratacion": fila.get("organo_contratacion"),
            "importe": fila.get("importe"),
            "fecha_limite": fila.get("fecha_limite"),
            "url": fila.get("url"),
            "aviso": payload.get("aviso_titulo"),
            "aviso_detalle": payload.get("aviso_detalle"),
        }
        grupos.setdefault(clave, (etiqueta, []))[1].append(licitacion)

    def _orden(clave: str) -> tuple[int, str]:
        return (SUBTIPOS.index(clave), "") if clave in SUBTIPOS else (len(SUBTIPOS), clave)

    return [
        BloqueDigest(etiqueta=etiqueta, licitaciones=lics, es_aviso=True)
        for clave, (etiqueta, lics) in sorted(grupos.items(), key=lambda kv: _orden(kv[0]))
    ]


def etiqueta_de_regla(
    *,
    nombre: str | None,
    keyword: str | None,
    cpv: str | None,
    min_importe: float | None,
    ccaa: str | None,
) -> str:
    """Cómo se llama la regla en el correo: su nombre, o sus criterios."""
    if nombre:
        return str(nombre)
    partes: list[str] = []
    if keyword:
        partes.append(f"«{keyword}»")
    if cpv:
        partes.append(f"CPV {cpv}")
    if min_importe:
        partes.append(f"≥ {_importe(min_importe)}")
    if ccaa:
        partes.append(str(ccaa))
    return " · ".join(partes) or "tu regla"


def _importe(valor: Any) -> str:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return "—"
    return f"{numero:,.0f} €".replace(",", ".")


def _fecha(valor: Any) -> str:
    texto = str(valor or "")[:10]
    return texto or "—"


def enlace_ficha(licitacion: dict[str, Any], base_url: str | None) -> str | None:
    """A la ficha de la consola si se conoce el sitio; si no, al anuncio oficial."""
    id_externo = str(licitacion.get("id_externo") or "")
    if base_url and id_externo:
        from urllib.parse import quote

        return f"{base_url}/detalle?lic={quote(id_externo, safe='')}"
    url = licitacion.get("url")
    return str(url) if url else None


def _plural_avisos(n: int) -> str:
    return "novedad" if n == 1 else "novedades"


def asunto_digest(frecuencia: str, total: int, *, avisos: int = 0) -> str:
    """Asunto del digest. ``total`` son las licitaciones nuevas de reglas y
    ``avisos`` las novedades sobre lo seguido (F5.3): se cuentan aparte porque
    un plazo ampliado no es una licitación nueva."""
    cuando = _ETIQUETA_FRECUENCIA.get(frecuencia, "")
    plural = "licitación nueva" if total == 1 else "licitaciones nuevas"
    if avisos and not total:
        return f"TenderFlow · {avisos} {_plural_avisos(avisos)} en lo que sigues".strip()
    if avisos:
        return (
            f"TenderFlow · {total} {plural} {cuando} y {avisos} {_plural_avisos(avisos)}"
        ).strip()
    return f"TenderFlow · {total} {plural} {cuando}".strip()


def _cabecera(bloques: list[BloqueDigest], cuando: str) -> str:
    nuevas = sum(len(b.licitaciones) for b in bloques if not b.es_aviso)
    avisos = sum(len(b.licitaciones) for b in bloques if b.es_aviso)
    reglas = f"{nuevas} licitación(es) nueva(s) {cuando} para tus reglas de seguimiento."
    if not avisos:
        return reglas
    seguidos = f"{avisos} {_plural_avisos(avisos)} en los expedientes que sigues."
    return seguidos if not nuevas else f"{reglas} Además, {seguidos}"


def render_digest(
    *,
    bloques: list[BloqueDigest],
    frecuencia: str,
    base_url: str | None,
    baja_url: str | None,
    max_por_bloque: int = _MAX_POR_BLOQUE,
) -> tuple[str, str]:
    """Devuelve ``(texto_plano, html)`` del digest."""
    cuando = _ETIQUETA_FRECUENCIA.get(frecuencia, "")
    cabecera = _cabecera(bloques, cuando)

    texto: list[str] = [cabecera, ""]
    partes_html: list[str] = [
        '<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;'
        'max-width:640px;margin:0 auto;color:#1f2733;line-height:1.5">',
        f'<p style="font-size:15px">{html.escape(cabecera)}</p>',
    ]

    for bloque in bloques:
        texto.append(f"== {bloque.etiqueta} ({len(bloque.licitaciones)}) ==")
        partes_html.append(
            '<h3 style="margin:20px 0 8px;font-size:14px;color:#55606e;'
            f'text-transform:uppercase;letter-spacing:.04em">{html.escape(bloque.etiqueta)}'
            f' <span style="font-weight:normal">· {len(bloque.licitaciones)}</span></h3>'
        )
        for lic in bloque.licitaciones[:max_por_bloque]:
            titulo = str(lic.get("titulo") or lic.get("id_externo") or "Sin título")
            organo = str(lic.get("organo_contratacion") or "Órgano no publicado")
            importe = _importe(lic.get("importe")) if lic.get("importe") else "—"
            plazo = _fecha(lic.get("fecha_limite"))
            extras = " · ".join(str(x) for x in (lic.get("ccaa"), lic.get("tecnologia")) if x)
            enlace = enlace_ficha(lic, base_url)

            aviso = " — ".join(str(x) for x in (lic.get("aviso"), lic.get("aviso_detalle")) if x)

            texto.append(f"* {titulo}")
            if aviso:
                texto.append(f"  {aviso}")
            texto.append(
                f"  {organo} | {importe} | plazo {plazo}" + (f" | {extras}" if extras else "")
            )
            if enlace:
                texto.append(f"  {enlace}")

            titulo_html = html.escape(titulo)
            if enlace:
                titulo_html = (
                    f'<a href="{html.escape(enlace, quote=True)}" '
                    f'style="color:#1d4ed8;text-decoration:none">{titulo_html}</a>'
                )
            partes_html.append(
                '<div style="padding:10px 12px;margin:0 0 8px;border:1px solid #e5e8ec;'
                'border-radius:8px">'
                f'<div style="font-weight:600">{titulo_html}</div>'
                + (
                    f'<div style="font-size:13px;color:#1f2733">{html.escape(aviso)}</div>'
                    if aviso
                    else ""
                )
                + f'<div style="font-size:13px;color:#55606e">{html.escape(organo)}</div>'
                f'<div style="font-size:13px"><strong>{html.escape(importe)}</strong>'
                f" · plazo {html.escape(plazo)}"
                + (f" · {html.escape(extras)}" if extras else "")
                + "</div></div>"
            )
        resto = len(bloque.licitaciones) - max_por_bloque
        if resto > 0:
            texto.append(f"  … y {resto} más.")
            partes_html.append(
                f'<p style="font-size:13px;color:#55606e">… y {resto} más en la consola.</p>'
            )
        texto.append("")

    if base_url:
        texto.append(f"Mi Watchlist: {base_url}/mi-watchlist")
        partes_html.append(
            f'<p style="font-size:13px"><a href="{html.escape(base_url, quote=True)}/mi-watchlist" '
            'style="color:#1d4ed8">Gestionar mis reglas</a></p>'
        )
    if baja_url:
        texto.append(f"Dejar de recibir estos correos: {baja_url}")
        partes_html.append(
            '<p style="font-size:12px;color:#8a93a0;margin-top:24px">'
            f'<a href="{html.escape(baja_url, quote=True)}" style="color:#8a93a0">'
            "Dejar de recibir estos correos</a> (pausa tus reglas; se reactivan desde "
            "Mi Watchlist).</p>"
        )
    partes_html.append(
        '<p style="color:#8a93a0;font-size:12px;margin-top:16px">TenderFlow · '
        "inteligencia de licitaciones públicas de tecnología</p></body></html>"
    )
    return "\n".join(texto).rstrip() + "\n", "".join(partes_html)


# ── Correo de un solo evento (S4.6) ─────────────────────────────────────────
#
# El digest agrupa coincidencias de reglas; una asignación o un comentario no
# es eso: es un hecho suelto que exige una respuesta de una persona concreta.
# Reutilizar `render_digest` para uno solo daba un correo con cabecera de
# «N licitaciones nuevas» y un bloque de uno, que se lee como spam.


def asunto_evento(titulo_evento: str, licitacion_id: str | None) -> str:
    """Asunto del correo de un evento personal."""
    if licitacion_id:
        return f"TenderFlow · {titulo_evento} ({licitacion_id})"
    return f"TenderFlow · {titulo_evento}"


def render_evento(
    *,
    titulo: str,
    cuerpo: str,
    licitacion_id: str | None,
    base_url: str | None = None,
) -> tuple[str, str]:
    """Devuelve ``(texto_plano, html)`` del correo de un evento.

    Sin motor de plantillas, igual que el digest y el correo de acceso
    concedido: el proyecto no tiene Jinja y añadir una dependencia para un
    tercer correo no compensa.
    """
    enlace = (
        enlace_ficha({"id_externo": licitacion_id}, base_url)
        if licitacion_id and base_url
        else None
    )

    texto = [titulo, "", cuerpo]
    if enlace:
        texto.extend(["", enlace])
    texto.extend(["", "Gestiona qué avisos recibes por correo en tu perfil de TenderFlow."])

    titulo_html = html.escape(titulo)
    if enlace:
        titulo_html = (
            f'<a href="{html.escape(enlace, quote=True)}" '
            f'style="color:#1d4ed8;text-decoration:none">{titulo_html}</a>'
        )
    partes = [
        '<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;'
        'max-width:640px;margin:0 auto;color:#1f2733;line-height:1.5">',
        f'<p style="font-size:15px;font-weight:600">{titulo_html}</p>',
        f'<p style="font-size:14px;color:#55606e">{html.escape(cuerpo)}</p>',
        '<p style="color:#8a93a0;font-size:12px;margin-top:24px">TenderFlow · '
        "gestiona qué avisos recibes por correo en tu perfil.</p></body></html>",
    ]
    return "\n".join(texto).rstrip() + "\n", "".join(partes)


# ── Baja de los correos ─────────────────────────────────────────────────────
# El enlace del pie pausa todas las reglas de quien lo pulsa sin pedirle sesión:
# quien quiere dejar de recibir correo no quiere antes hacer login. Lo que
# autoriza la acción es una firma HMAC del ``user_key`` (``shared/signing``,
# con rotación por ``kid``), y el ``user_key`` es un hash opaco, no un dato
# personal. La firma sólo sirve para esto —el endpoint no hace otra cosa— así
# que un enlace filtrado, como mucho, pausa unas reglas que se reactivan desde
# Mi Watchlist.

_PREFIJO_BAJA = b"baja-alertas:"


def token_de_baja(user_key: str) -> str | None:
    """Firma del ``user_key`` para el enlace de baja, o ``None`` si no hay claves."""
    if not user_key:
        return None
    try:
        from shared.signing import sign

        return sign(_PREFIJO_BAJA + user_key.encode("utf-8"))
    except Exception:
        # Sin firma el correo sale sin pie de baja, que es un correo peor pero
        # entregable. Se registra porque «no hay enlace de baja» y «las claves
        # de firma están mal configuradas» son indistinguibles en el buzón.
        log.warning("email_digest_token_baja_failed", exc_info=True)
        return None


def verificar_token_de_baja(user_key: str, token: str) -> bool:
    if not user_key or not token:
        return False
    try:
        from shared.signing import verify

        return verify(_PREFIJO_BAJA + user_key.encode("utf-8"), token)
    except Exception:
        # Fail-closed: sin verificación no se pausa nada. Se registra porque un
        # fallo del verificador se ve igual que una firma falsificada, y son
        # dos incidentes muy distintos.
        log.warning("email_digest_verificacion_baja_failed", exc_info=True)
        return False


def url_de_baja_alertas(user_key: str, base_url: str | None) -> str | None:
    """URL absoluta del enlace de baja, o ``None`` si no se puede construir."""
    token = token_de_baja(user_key)
    if token is None or not base_url:
        return None
    from urllib.parse import urlencode

    return f"{base_url}/api/v1/watchlist/rules/baja?{urlencode({'k': user_key, 't': token})}"


# ── Baja de un tipo concreto de notificación (T6) ───────────────────────────
#
# La baja de arriba pausa **todas las reglas de watchlist**: es la del digest,
# y para el digest es correcta. Para cualquier otro correo no lo es, y el
# informe semanal se entregó apuntando ahí. Una persona que pulsaba «dejar de
# recibir este informe» —o cuyo Gmail lo hacía por ella, que RFC 8058 es un
# POST automático— perdía todas sus alertas de licitaciones y **seguía**
# recibiendo el informe, porque su opt-out vive en `notification_preferences`.
#
# Esto es la baja que sí corresponde: apaga el canal `email` de un tipo
# concreto y no toca nada más.

#: Prefijo propio: un token de esta baja no puede valer para la de watchlist
#: ni al revés, aunque las dos firmen con la misma clave.
_PREFIJO_BAJA_TIPO = b"baja-notificacion:"


def _mensaje_baja_tipo(user_id: int, tipo: str) -> bytes:
    return _PREFIJO_BAJA_TIPO + f"{int(user_id)}:{tipo}".encode()


def token_de_baja_de_tipo(user_id: int, tipo: str) -> str | None:
    """Firma ``(user_id, tipo)``, o ``None`` si no hay claves.

    Firma el ``user_id`` y no la identidad heredada: es lo que recibe
    ``notification_preferences.guardar`` y lo que D18/T4 deja en pie.
    """
    try:
        from shared.signing import sign

        return sign(_mensaje_baja_tipo(user_id, tipo))
    except Exception:
        log.warning("baja_tipo_token_failed", tipo=tipo, exc_info=True)
        return None


def verificar_token_de_baja_de_tipo(user_id: int, tipo: str, token: str) -> bool:
    try:
        from shared.signing import verify

        return verify(_mensaje_baja_tipo(user_id, tipo), token)
    except Exception:
        log.warning("baja_tipo_verificacion_failed", tipo=tipo, exc_info=True)
        return False


def url_de_baja_de_tipo(user_id: int | None, tipo: str, base_url: str | None) -> str | None:
    """Enlace absoluto que apaga el correo de ``tipo`` para esa persona.

    ``None`` cuando no hay a quién apagárselo: un destinatario que no es cuenta
    de la aplicación —una lista de distribución, el buzón de dirección— no
    tiene preferencias, y ofrecerle un enlace de baja que no hace nada es peor
    que no ofrecerle ninguno.
    """
    if user_id is None or not base_url:
        return None
    token = token_de_baja_de_tipo(user_id, tipo)
    if token is None:
        return None
    from urllib.parse import urlencode

    consulta = urlencode({"u": int(user_id), "tipo": tipo, "t": token})
    return f"{base_url}/api/v1/notifications/baja?{consulta}"
