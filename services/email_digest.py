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

**El resumen como producto (B3 del plan 2026-10).** Por licitación el correo
dice lo que hace falta para decidir si abrirla: la fecha límite, el importe
base **sin IVA** —o «base desconocida» cuando la fila no la declara
(ADR-032: nunca se presenta un importe de base ignorada como si fuera la
base)—, hasta tres requisitos de solvencia de la ficha del pliego y, si se
puede calcular, el veredicto del checklist frente a la capacidad de la
organización, con el enlace a la ficha. Los requisitos y el checklist los
calcula ``services.digest_pliego`` (con su SQL en ``db/``) y llegan aquí ya
hechos, en la clave ``pliego`` de cada licitación. El tamaño del correo está
acotado por bloque y en total (:data:`_MAX_POR_BLOQUE`, :data:`_MAX_TOTAL`).
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, TypedDict, cast

from observability.logging import get_logger
from services.email_html import (
    CERRAR_DOCUMENTO,
    ESTILO_ENLACE,
    ESTILO_PIE,
    PAPEL,
    SECUNDARIO,
    abrir_documento,
    contar,
)

log = get_logger(__name__)

_MAX_POR_BLOQUE = 10
#: Techo de licitaciones en un correo, sumando todos los bloques. Con la
#: alerta por defecto (hasta cinco reglas) más las del usuario y los avisos,
#: diez por bloque podían ser sesenta tarjetas: lo que sobra se cuenta y se
#: manda a la consola.
_MAX_TOTAL = 30
#: Requisitos de solvencia por licitación, y su largo máximo en caracteres.
MAX_REQUISITOS = 3
_MAX_LARGO_REQUISITO = 140
_ETIQUETA_FRECUENCIA = {
    "immediate": "nuevas ahora",
    "daily": "de hoy",
    "weekly": "de la semana",
}


class RequisitoDigest(TypedDict):
    """Un requisito de solvencia tal y como lo pinta el correo."""

    #: «Solvencia económica» / «Solvencia técnica».
    familia: str
    texto: str
    #: ``cumple | no_cumple | desconocido``, o ``None`` cuando no hay
    #: capacidad declarada contra la que contrastarlo.
    veredicto: str | None


class ChecklistDigest(TypedDict):
    """El checklist frente a la capacidad de la organización, resumido."""

    veredicto: str
    cumple: int
    no_cumple: int
    desconocido: int


class PliegoDigest(TypedDict):
    """Lo que el correo cuenta de la ficha del pliego de una licitación."""

    requisitos: list[RequisitoDigest]
    #: ``None`` cuando no se puede calcular (sin requisitos o sin capacidad).
    checklist: ChecklistDigest | None


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
    #: Organización de la regla: contra su capacidad se calcula el checklist
    #: (B3). ``None`` en los avisos y en las entradas legadas.
    organization_id: int | None = None


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
            "importe_tipo": fila.get("importe_tipo"),
            "importe_base_sin_iva": fila.get("importe_base_sin_iva"),
            "importe_con_iva": fila.get("importe_con_iva"),
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


def _positivo(valor: object) -> float | None:
    """``valor`` como número positivo, o ``None``. ``numeric`` llega como ``Decimal``."""
    if isinstance(valor, bool) or not isinstance(valor, int | float | str | Decimal):
        return None
    try:
        numero = float(valor)
    except ValueError:
        return None
    return numero if numero > 0 else None


def importe_base(licitacion: Mapping[str, object]) -> str:
    """El importe base sin IVA, o «base desconocida». Nunca mezcla bases.

    En este orden (ADR-032 y ``mcp_server/glosario.md`` §2):

    1. ``importe_base_sin_iva``: es la base sin IVA por definición.
    2. ``importe`` cuando ``importe_tipo = 'sin_iva'``: la fila declara que su
       importe es esa base.
    3. ``importe_tipo = 'con_iva'``: la base no se sabe, pero sí el total con
       IVA, y se dice como tal.
    4. Lo demás —``desconocido`` o ``NULL``, el 42 % del corpus el 2026-10-26—
       es «base desconocida», sin cifra: el ``importe`` histórico mezcla bases
       y enseñarlo pelado sería presentar como base algo que puede llevar IVA.
    """
    tipo = str(licitacion.get("importe_tipo") or "desconocido")
    base = _positivo(licitacion.get("importe_base_sin_iva"))
    if base is None and tipo == "sin_iva":
        base = _positivo(licitacion.get("importe"))
    if base is not None:
        return f"{_importe(base)} sin IVA"
    if tipo == "con_iva":
        total = _positivo(licitacion.get("importe_con_iva")) or _positivo(licitacion.get("importe"))
        if total is not None:
            return f"base desconocida ({_importe(total)} con IVA)"
    return "base desconocida"


def visibles_por_bloque(
    bloques: list[BloqueDigest],
    *,
    max_por_bloque: int = _MAX_POR_BLOQUE,
    max_total: int = _MAX_TOTAL,
) -> list[int]:
    """Cuántas licitaciones de cada bloque caben en el correo.

    Es la única definición del recorte: la usa :func:`render_digest` para
    pintar y ``services.digest_pliego`` para no cargar fichas que no se van a
    enseñar.
    """
    restantes = max(0, max_total)
    cuantas: list[int] = []
    for bloque in bloques:
        n = min(len(bloque.licitaciones), max(0, max_por_bloque), restantes)
        cuantas.append(n)
        restantes -= n
    return cuantas


_ETIQUETA_VEREDICTO = {
    "cumple": "cumple",
    "no_cumple": "no cumple",
    "desconocido": "sin dato suficiente",
}


def _recortar(texto: str, largo: int = _MAX_LARGO_REQUISITO) -> str:
    limpio = " ".join(texto.split())
    return limpio if len(limpio) <= largo else limpio[: largo - 1].rstrip() + "…"


def lineas_de_pliego(pliego: PliegoDigest | None) -> list[str]:
    """Las líneas del pliego de una licitación, en texto plano. Pura.

    Sin ficha ni condiciones oficiales no hay nada que contar y devuelve
    ``[]``: el correo no dice «sin requisitos» de lo que no se ha leído.
    """
    if not pliego:
        return []
    lineas: list[str] = []
    requisitos = list(pliego.get("requisitos") or [])[:MAX_REQUISITOS]
    if requisitos:
        lineas.append("Solvencia que pide el pliego:")
        for req in requisitos:
            veredicto = req.get("veredicto")
            sufijo = f" ({_ETIQUETA_VEREDICTO.get(veredicto, veredicto)})" if veredicto else ""
            lineas.append(f"- {req['familia']}: {_recortar(str(req['texto']))}{sufijo}")
    checklist = pliego.get("checklist")
    if checklist:
        veredicto = _ETIQUETA_VEREDICTO.get(checklist["veredicto"], checklist["veredicto"])
        lineas.append(
            f"Checklist frente a la capacidad de tu organización: {veredicto} "
            f"({checklist['cumple']} cumple · {checklist['no_cumple']} no cumple · "
            f"{checklist['desconocido']} sin dato)"
        )
    return lineas


def enlace_ficha(licitacion: Mapping[str, object], base_url: str | None) -> str | None:
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
    reglas = (
        f"{contar(nuevas, 'licitación nueva', 'licitaciones nuevas')} {cuando} "
        "para tus reglas de seguimiento."
    )
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
    max_total: int = _MAX_TOTAL,
) -> tuple[str, str]:
    """Devuelve ``(texto_plano, html)`` del digest."""
    cuando = _ETIQUETA_FRECUENCIA.get(frecuencia, "")
    cabecera = _cabecera(bloques, cuando)
    cupo = visibles_por_bloque(bloques, max_por_bloque=max_por_bloque, max_total=max_total)

    texto: list[str] = [cabecera, ""]
    partes_html: list[str] = [
        abrir_documento(),
        f'<p style="font-size:15px">{html.escape(cabecera)}</p>',
    ]

    for bloque, visibles in zip(bloques, cupo, strict=True):
        texto.append(f"== {bloque.etiqueta} ({len(bloque.licitaciones)}) ==")
        partes_html.append(
            f'<h3 style="margin:20px 0 8px;font-size:14px;color:{SECUNDARIO};'
            f'text-transform:uppercase;letter-spacing:.04em">{html.escape(bloque.etiqueta)}'
            f' <span style="font-weight:normal">· {len(bloque.licitaciones)}</span></h3>'
        )
        for lic in bloque.licitaciones[:visibles]:
            tarjeta = _datos_tarjeta(lic, base_url)
            texto.extend(_tarjeta_texto(tarjeta))
            partes_html.append(_tarjeta_html(tarjeta))
        resto = len(bloque.licitaciones) - visibles
        if resto > 0:
            texto.append(f"  … y {resto} más.")
            partes_html.append(f'<p style="color:{SECUNDARIO}">… y {resto} más en la consola.</p>')
        texto.append("")

    if base_url:
        texto.append(f"Mi Watchlist: {base_url}/mi-watchlist")
        partes_html.append(
            f'<p><a href="{html.escape(base_url, quote=True)}/mi-watchlist" '
            f'style="{ESTILO_ENLACE}">Gestionar mis reglas</a></p>'
        )
    if baja_url:
        texto.append(f"Dejar de recibir estos correos: {baja_url}")
        partes_html.append(
            f'<p style="{ESTILO_PIE};margin-top:24px">'
            f'<a href="{html.escape(baja_url, quote=True)}" style="color:{SECUNDARIO}">'
            "Dejar de recibir estos correos</a> (pausa tus reglas; se reactivan desde "
            "Mi Watchlist).</p>"
        )
    partes_html.append(
        f'<p style="{ESTILO_PIE};margin-top:16px">TenderFlow · '
        "inteligencia de licitaciones públicas de tecnología</p>" + CERRAR_DOCUMENTO
    )
    return "\n".join(texto).rstrip() + "\n", "".join(partes_html)


@dataclass(frozen=True)
class _Tarjeta:
    """Lo que pintan las dos versiones de una tarjeta, calculado una vez."""

    titulo: str
    organo: str
    importe: str
    plazo: str
    extras: str
    enlace: str | None
    aviso: str
    pliego: list[str]


def _datos_tarjeta(lic: Mapping[str, object], base_url: str | None) -> _Tarjeta:
    pliego = lic.get("pliego")
    return _Tarjeta(
        titulo=str(lic.get("titulo") or lic.get("id_externo") or "Sin título"),
        organo=str(lic.get("organo_contratacion") or "Órgano no publicado"),
        importe=importe_base(lic),
        plazo=_fecha(lic.get("fecha_limite")),
        extras=" · ".join(str(x) for x in (lic.get("ccaa"), lic.get("tecnologia")) if x),
        enlace=enlace_ficha(lic, base_url),
        aviso=" — ".join(str(x) for x in (lic.get("aviso"), lic.get("aviso_detalle")) if x),
        pliego=lineas_de_pliego(cast(PliegoDigest, pliego) if isinstance(pliego, dict) else None),
    )


def _tarjeta_texto(t: _Tarjeta) -> list[str]:
    lineas = [f"* {t.titulo}"]
    if t.aviso:
        lineas.append(f"  {t.aviso}")
    lineas.append(
        f"  {t.organo} | {t.importe} | fecha límite {t.plazo}"
        + (f" | {t.extras}" if t.extras else "")
    )
    lineas.extend(f"  {linea}" for linea in t.pliego)
    if t.enlace:
        lineas.append(f"  Ficha: {t.enlace}")
    return lineas


def _tarjeta_html(t: _Tarjeta) -> str:
    titulo_html = html.escape(t.titulo)
    enlace_html = ""
    if t.enlace:
        href = html.escape(t.enlace, quote=True)
        titulo_html = (
            f'<a href="{href}" style="{ESTILO_ENLACE};text-decoration:none">{titulo_html}</a>'
        )
        enlace_html = (
            f'<div style="margin-top:6px"><a href="{href}" style="{ESTILO_ENLACE}">'
            "Abrir la ficha</a></div>"
        )
    pliego_html = ""
    if t.pliego:
        pliego_html = (
            f'<div style="margin-top:6px;color:{SECUNDARIO}">'
            + "<br>".join(html.escape(linea) for linea in t.pliego)
            + "</div>"
        )
    return (
        f'<div style="padding:10px 12px;margin:0 0 8px;border:1px solid {PAPEL};'
        'border-radius:8px">'
        f'<div style="font-weight:600">{titulo_html}</div>'
        + (f"<div>{html.escape(t.aviso)}</div>" if t.aviso else "")
        + f'<div style="color:{SECUNDARIO}">{html.escape(t.organo)}</div>'
        f"<div><strong>{html.escape(t.importe)}</strong>"
        f" · fecha límite {html.escape(t.plazo)}"
        + (f" · {html.escape(t.extras)}" if t.extras else "")
        + "</div>"
        + pliego_html
        + enlace_html
        + "</div>"
    )


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
            f'style="{ESTILO_ENLACE};text-decoration:none">{titulo_html}</a>'
        )
    partes = [
        abrir_documento(),
        f'<p style="font-size:15px;font-weight:600">{titulo_html}</p>',
        f'<p style="color:{SECUNDARIO}">{html.escape(cuerpo)}</p>',
        f'<p style="{ESTILO_PIE};margin-top:24px">TenderFlow · '
        "gestiona qué avisos recibes por correo en tu perfil.</p>" + CERRAR_DOCUMENTO,
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
