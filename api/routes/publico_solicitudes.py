"""Ruta ``POST /api/v1/publico/solicitudes-acceso`` — cola de peticiones de acceso.

Único endpoint público de **escritura** de la API, y por eso todo aquí es
deliberado.

**Cuelga de ``/publico`` por la misma razón que el resto de la superficie
anónima**: ``api/app.py`` registra al final un catch-all
``/api/v1/licitaciones/{id_externo:path}`` con ``require_any_auth``, y
cualquier ruta pública bajo ese prefijo quedaría ensombrecida sin un solo error
en el arranque. Además ``scripts/check_public_surface.py`` escanea
``api/routes/publico*.py``, así que este fichero entra gratis en ese guard.

**Acepta ``application/x-www-form-urlencoded``, no JSON.** El formulario de la
landing es HTML puro dentro de un Server Component: sin JavaScript de cliente,
sin ``fetch`` y sin hidratación. Un ``<form method="post">`` nativo envía
form-encoded, y a cambio el embudo funciona con el JavaScript bloqueado, que es
exactamente el escenario en el que un ``mailto:`` también fallaba.

El cuerpo se parsea con ``urllib.parse.parse_qs`` y no con ``Form()`` de
FastAPI, que exigiría añadir ``python-multipart`` a las dependencias. Para un
único endpoint que sólo recibe urlencoded, tres líneas de biblioteca estándar
evitan un parser nuevo en el árbol de dependencias —y la regeneración de locks
con hashes que arrastra—. ``multipart/form-data`` se rechaza explícitamente:
aquí no se suben ficheros.

**Responde 303 y nunca 5xx.** ``scripts/fuzz_api_contract.py`` mantiene
``KNOWN_5XX`` a cero: entrada de internet, salida limpia. Un envío inválido no
es un error del servidor, es una redirección a la misma página de gracias con
``?estado=<motivo>``. Y como el navegador sigue la redirección, el usuario nunca
ve JSON.

Ese "nunca ve JSON" tenía una fuga que no se veía desde este fichero: el corte
por rate limit ocurre en ``RateLimitMiddleware``, **antes** del router, y
devolvía el ``application/problem+json`` de RFC 7807 en crudo al navegador —una
oficina tras NAT o un reintento bastaban para provocarlo—. El middleware trata
ahora este path como caso propio y redirige con ``ESTADO_LIMITE``; los estados
los declara este módulo para que la página de gracias y la API no puedan
divergir.

**Avisa de lo que encola.** Una solicitud guardada y no vista no sirve de nada,
y la concesión de acceso es manual: sin aviso, el embudo terminaba en una fila
de Postgres que solo se descubría abriendo el panel. Se emite
``EVENTO_SOLICITUD_ACCESO`` por el sistema de webhooks existente —con su firma
HMAC y su allowlist anti-SSRF— y **sin el email ni el mensaje**: el aviso dice
que hay algo que atender, no quién lo pide. Va como ``BackgroundTasks``, o sea
después de enviar la respuesta, para que los cinco segundos de timeout por
entrega no los espere el visitante.

**Sin CSRF, a propósito.** ``require_csrf`` es una dependencia por endpoint que
sólo aplica cuando hay cookie de sesión (``api/routes/dual_auth.py``); este POST
es anónimo y no muta nada del usuario que lo envía. Lo que sí se comprueba es
que ``Origin``/``Referer``, **cuando vienen**, pertenezcan al propio sitio: no
es una defensa contra un atacante determinado —puede omitir la cabecera— pero
corta el envío cruzado casual desde un formulario alojado en otro dominio.

**Anti-abuso sin captcha.** La CSP de la superficie pública es
``connect-src 'self'``, así que un captcha de terceros no cargaría sin
relajarla. Lo que hay: un bucket de rate limit propio y estricto en
``api/middleware.py`` (no el de la superficie pública, que es de 600/min y
compartido con los rastreadores), y un campo trampa que ningún humano ve. Es
suficiente para una cola que revisa una persona y cuyo peor caso es borrar
filas — la concesión de acceso sigue siendo manual y fail-closed.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, BackgroundTasks, Request, status
from fastapi.responses import RedirectResponse

from api.concurrency import run_db
from config.settings import settings
from db.solicitudes_acceso import contar_pendientes, crear_solicitud
from db.webhooks import EVENTO_SOLICITUD_ACCESO, trigger_event
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["publico"])

# Página de gracias de la web. Relativa a propósito: así atraviesa el rewrite
# de Vercel y funciona igual en local, en preview y en producción.
_DESTINO_OK = "/solicitud-recibida"

# Estados de error que entiende la página de gracias.
#
# Un único `?estado=error` obligaba a un texto genérico ("revisa que el email
# sea correcto y que hayas aceptado…") aunque aquí se sabe perfectamente cuál
# de las dos cosas falló. Diferenciarlos convierte "vuelve a intentarlo" en
# "revisa esto", que es la diferencia entre recuperar el envío y perderlo.
#
# Lo que **no** viaja de vuelta es lo que el visitante escribió: el email es un
# dato personal y no se pone en una query string, que acaba en logs de acceso,
# en el `Referer` de la siguiente petición y en el historial del navegador. El
# coste es que hay que reescribir el formulario; es el correcto.
ESTADO_EMAIL = "email"
ESTADO_CONSENTIMIENTO = "consentimiento"
ESTADO_ERROR = "error"
#: Cuota agotada. Lo emite `RateLimitMiddleware`, no esta ruta: el corte por
#: rate limit ocurre antes del router y sin él el visitante veía el
#: `application/problem+json` crudo, que es justo lo que este módulo evita en
#: todos sus demás caminos.
ESTADO_LIMITE = "limite"


def destino_error(motivo: str) -> str:
    """URL de la página de gracias para un envío que no prosperó."""
    return f"{_DESTINO_OK}?estado={motivo}"


_DESTINO_ERROR = destino_error(ESTADO_ERROR)

# Validación de email deliberadamente laxa: el objetivo es descartar la errata
# evidente, no decidir si un buzón existe. Un patrón estricto rechaza
# direcciones válidas y el coste de un falso negativo aquí es perder un lead.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")

_MAX_EMAIL = 254  # RFC 5321
_MAX_EMPRESA = 200
_MAX_MENSAJE = 2000

# Orígenes de los que se acepta el envío. Sólo se comprueba si la cabecera
# viene; ver el docstring del módulo.
_ORIGENES_DEV = ("http://localhost:3000", "http://127.0.0.1:3000")


def _origenes_validos() -> set[str]:
    permitidos = {
        origen.strip().rstrip("/")
        for origen in (settings.CORS_ALLOWED_ORIGINS or "").split(",")
        if origen.strip()
    }
    if settings.ENV == "dev":
        permitidos.update(_ORIGENES_DEV)
    return permitidos


def _origen_ajeno(request: Request) -> bool:
    """``True`` si la petición declara un origen y no es de los nuestros."""
    permitidos = _origenes_validos()
    if not permitidos:
        # Sin configuración no se puede afirmar que un origen sea ajeno, y
        # rechazar por defecto dejaría el formulario roto en cuanto alguien
        # despliegue sin CORS_ALLOWED_ORIGINS. El rate limit sigue en pie.
        return False
    declarado = request.headers.get("origin") or request.headers.get("referer")
    if not declarado:
        return False
    partes = urlparse(declarado)
    if not partes.scheme or not partes.netloc:
        return False
    return f"{partes.scheme}://{partes.netloc}" not in permitidos


def _limpiar(valor: str | None, maximo: int) -> str | None:
    if valor is None:
        return None
    recortado = valor.strip()[:maximo]
    return recortado or None


# Sólo se acepta el envío nativo de un formulario HTML.
_TIPO_FORMULARIO = "application/x-www-form-urlencoded"


def _campo(datos: dict[str, list[str]], nombre: str) -> str:
    """Primer valor de un campo del formulario, o cadena vacía."""
    valores = datos.get(nombre)
    return valores[0] if valores else ""


def _avisar_operador(solicitud_id: int, empresa: str | None, origen: str | None) -> None:
    """Anuncia una solicitud nueva por webhook.

    Sin esto el embudo terminaba en una fila de Postgres que nadie miraba: el
    formulario funcionaba, la cola crecía y la concesión de acceso —que es
    manual— dependía de que alguien se acordara de abrir el panel. Se reutiliza
    el sistema de webhooks que ya existe, con su firma HMAC y su allowlist
    anti-SSRF, en vez de añadir un canal nuevo.

    **No viaja ni el email ni el mensaje.** Un webhook sale del sistema hacia un
    endpoint configurado por el operador, y el aviso no necesita el dato
    personal para cumplir su función: dice que hay algo que atender y cuántas
    esperan; la dirección se lee en el panel, que ya exige ser admin. `empresa`
    sí va, porque es dato de negocio y es lo que hace accionable el aviso.

    Corre como ``BackgroundTasks``, o sea **después** de enviar la respuesta:
    la entrega tiene cinco segundos de timeout por webhook y el visitante no
    tiene por qué esperarlos. Y no propaga: un webhook mal configurado no puede
    convertirse en un fallo de un formulario público.
    """
    try:
        entregados = trigger_event(
            EVENTO_SOLICITUD_ACCESO,
            {
                "id": solicitud_id,
                "empresa": empresa,
                "origen": origen,
                "pendientes": contar_pendientes(),
            },
        )
        log.info("solicitud_acceso_aviso", solicitud_id=solicitud_id, entregados=entregados)
    except Exception:
        log.exception("solicitud_acceso_aviso_fallido", solicitud_id=solicitud_id)


@router.post(
    "/publico/solicitudes-acceso",
    status_code=status.HTTP_303_SEE_OTHER,
    summary="Registra una solicitud de acceso enviada desde la web pública",
    response_class=RedirectResponse,
)
async def solicitar_acceso(request: Request, tareas: BackgroundTasks) -> RedirectResponse:
    if not request.headers.get("content-type", "").startswith(_TIPO_FORMULARIO):
        return RedirectResponse(_DESTINO_ERROR, status_code=status.HTTP_303_SEE_OTHER)

    # El límite de 1 MB de cuerpo ya lo aplica el middleware de la aplicación.
    crudo = await request.body()
    datos = parse_qs(crudo.decode("utf-8", errors="replace"), keep_blank_values=True)

    # Campo trampa: invisible para una persona, irresistible para un bot que
    # rellena todo lo que encuentra. Si viene con algo se responde el mismo 303
    # de éxito y no se guarda nada — decírselo sólo le enseñaría a evitarlo.
    if _campo(datos, "website").strip():
        log.info("solicitud_acceso_honeypot")
        return RedirectResponse(_DESTINO_OK, status_code=status.HTTP_303_SEE_OTHER)

    if _origen_ajeno(request):
        log.warning("solicitud_acceso_origen_ajeno")
        return RedirectResponse(_DESTINO_ERROR, status_code=status.HTTP_303_SEE_OTHER)

    correo = _campo(datos, "email").strip()[:_MAX_EMAIL]
    if not _EMAIL.match(correo):
        return RedirectResponse(destino_error(ESTADO_EMAIL), status_code=status.HTTP_303_SEE_OTHER)

    # El consentimiento es obligatorio: sin él no hay base para guardar un dato
    # de contacto, así que el envío se rechaza en lugar de guardarse "por si
    # acaso". Un checkbox HTML sin marcar ni siquiera se envía.
    if not _campo(datos, "consentimiento").strip():
        return RedirectResponse(
            destino_error(ESTADO_CONSENTIMIENTO), status_code=status.HTTP_303_SEE_OTHER
        )

    empresa = _limpiar(_campo(datos, "empresa"), _MAX_EMPRESA)
    origen = _limpiar(_campo(datos, "origen"), 40)

    try:
        solicitud_id = await run_db(
            crear_solicitud,
            email=correo,
            empresa=empresa,
            mensaje=_limpiar(_campo(datos, "mensaje"), _MAX_MENSAJE),
            origen=origen,
        )
    except Exception:
        # Nunca un 5xx desde una página pública: se registra para el operador y
        # el visitante recibe la misma redirección de error que un envío mal
        # formado. El fuzzer del contrato mantiene KNOWN_5XX a cero.
        log.exception("solicitud_acceso_error")
        return RedirectResponse(_DESTINO_ERROR, status_code=status.HTTP_303_SEE_OTHER)

    tareas.add_task(_avisar_operador, solicitud_id, empresa, origen)

    log.info("solicitud_acceso_registrada")
    return RedirectResponse(_DESTINO_OK, status_code=status.HTTP_303_SEE_OTHER)
