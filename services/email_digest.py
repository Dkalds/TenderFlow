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
    """Las coincidencias de una regla (o entrada legada) de la watchlist."""

    etiqueta: str
    licitaciones: list[dict[str, Any]] = field(default_factory=list)


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


def asunto_digest(frecuencia: str, total: int) -> str:
    cuando = _ETIQUETA_FRECUENCIA.get(frecuencia, "")
    plural = "licitación nueva" if total == 1 else "licitaciones nuevas"
    return f"TenderFlow · {total} {plural} {cuando}".strip()


def render_digest(
    *,
    bloques: list[BloqueDigest],
    frecuencia: str,
    base_url: str | None,
    baja_url: str | None,
    max_por_bloque: int = _MAX_POR_BLOQUE,
) -> tuple[str, str]:
    """Devuelve ``(texto_plano, html)`` del digest."""
    total = sum(len(b.licitaciones) for b in bloques)
    cuando = _ETIQUETA_FRECUENCIA.get(frecuencia, "")
    cabecera = f"{total} licitación(es) nueva(s) {cuando} para tus reglas de seguimiento."

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

            texto.append(f"* {titulo}")
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
                f'<div style="font-size:13px;color:#55606e">{html.escape(organo)}</div>'
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
