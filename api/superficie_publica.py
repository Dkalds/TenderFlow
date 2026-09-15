"""Qué parte de la API es un contrato con el cliente, y qué parte es interna.

El problema
-----------
La API declara más de doscientas operaciones y ``api/openapi.json`` las lleva
todas. Ese fichero es lo que se le acaba enseñando a un integrador, y en cuanto
alguien lo lee pasan dos cosas malas a la vez:

1. **Todo se vuelve promesa.** El endpoint de banderas de funcionalidad, el de
   administración de usuarios o el que alimenta una pestaña concreta de la
   consola quedan tan publicados como ``GET /licitaciones``. Cambiar cualquiera
   de ellos deja de ser refactorizar y pasa a ser romper a alguien — y nadie se
   entera hasta que ocurre.
2. **El cliente no sabe qué usar.** Doscientas operaciones sin distinción de
   soporte no son documentación: son un volcado. La pregunta «¿puedo construir
   sobre esto?» no tiene respuesta.

La decisión
-----------
Una lista explícita, aquí, de lo que **sí** es contrato. Con ella se hacen dos
cosas en ``scripts/export_openapi.py``:

* se estampa ``x-public: true`` en esas operaciones del spec completo, para que
  la marca viaje en el artefacto que ya existe; y
* se genera ``api/openapi-public.json``, que es el que se publica: sólo esas
  operaciones y sólo los esquemas que alcanzan.

Por qué una lista y no un ``openapi_extra`` en cada ruta
--------------------------------------------------------
La marca por ruta es más idiomática en FastAPI y se acerca más al código, pero
reparte la respuesta a «qué prometemos» entre treinta ficheros, donde nadie la
lee entera. Lo que hace falta aquí es justo lo contrario: **un sitio que un
humano pueda leer de arriba abajo antes de firmar un contrato**, con el motivo
al lado de cada línea. El riesgo de que la lista se desincronice del código lo
cubre ``tests/test_superficie_publica.py``, que falla si una operación
declarada ya no existe.

Qué **no** entra, y por qué
---------------------------
* **Analítica** (``/analytics/*``, ``/competitive/*``). Son agregados cuya
  forma cambia con el modelo de datos; publicarlos congela decisiones internas.
* **La vertical de oportunidades** (``/pursuits/*``). Es el CRM de la consola,
  con ``expected_version`` y estado de interfaz; su contrato es la pantalla.
* **Administración, auth de navegador, banderas, modelos, feedback.** Nada de
  eso es para un tercero.
* **``/publico/*``**, pese al nombre. Es la superficie **del sitio web** (SEO,
  sitemap, fichas indexables), no la API que un cliente integra. La
  coincidencia de nombre es desafortunada y ésta es la nota que lo aclara.
* **``/ask`` y las rutas de LLM.** Su coste por llamada y su contrato de
  respuesta todavía se mueven.

Cómo se cambia esta lista
-------------------------
Añadir es barato: una línea con su motivo. **Quitar no**: sacar una operación
de aquí es romper a quien la use, así que va por RFC con fecha, como la
retirada de los exports asíncronos (``docs/rfc/2026-09-03-...``). El test
pinchado avisa de las dos direcciones.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Extensión OpenAPI que marca una operación como contrato público.
EXTENSION = "x-public"


@dataclass(frozen=True, slots=True)
class OperacionPublica:
    """Una operación del contrato, con el motivo por el que lo es."""

    metodo: str
    ruta: str
    porque: str

    @property
    def clave(self) -> tuple[str, str]:
        return (self.metodo.lower(), self.ruta)


_P = OperacionPublica

#: El contrato. Ordenado por bloques, no alfabéticamente: se lee por temas.
SUPERFICIE_PUBLICA: tuple[OperacionPublica, ...] = (
    # ── El dato, que es el producto ────────────────────────────────────────
    _P("GET", "/api/v1/licitaciones", "el listado con filtros: la puerta de entrada"),
    _P("GET", "/api/v1/licitaciones/cursor", "paginación estable para volcados completos"),
    _P("POST", "/api/v1/licitaciones/search", "búsqueda avanzada; POST por el tamaño del cuerpo"),
    _P("POST", "/api/v1/licitaciones/bulk-get", "resolver N identificadores en una llamada"),
    _P("GET", "/api/v1/licitaciones/{id_externo}", "el detalle de un expediente"),
    _P(
        "GET",
        "/api/v1/licitaciones/{id_externo}/documentos",
        "los pliegos: sin esto el detalle es media respuesta",
    ),
    _P("GET", "/api/v1/adjudicaciones", "quién ganó qué, que es la otra mitad del corpus"),
    _P("GET", "/api/v1/empresas", "el censo de adjudicatarios"),
    _P("GET", "/api/v1/empresas/{empresa_id}", "la ficha de una empresa"),
    _P("GET", "/api/v1/resoluciones", "resoluciones de recursos asociadas a un expediente"),
    # ── Metadatos: sin esto los filtros se adivinan ────────────────────────
    _P("GET", "/api/v1/meta/filters", "los valores válidos de cada filtro, en vez de adivinarlos"),
    _P("GET", "/api/v1/meta/last-extraction", "hasta qué fecha llega el corpus"),
    # ── Salida ──────────────────────────────────────────────────────────────
    _P("GET", "/api/v1/exports/download", "CSV/Excel/PDF del listado con los filtros puestos"),
    _P("GET", "/api/v1/exports/calendario.ics", "los plazos en el calendario del cliente"),
    # ── Seguimiento ─────────────────────────────────────────────────────────
    _P("GET", "/api/v1/follows", "qué sigue el usuario (ADR-031)"),
    _P("POST", "/api/v1/follows", "seguir un expediente, una empresa, un órgano o un CPV"),
    _P("DELETE", "/api/v1/follows/{target_type}/{target_id}", "dejar de seguir"),
    _P("GET", "/api/v1/watchlist/items", "favoritos; sigue publicado hasta que lo retire su RFC"),
    _P("POST", "/api/v1/watchlist/items", "marcar un expediente como favorito"),
    _P("DELETE", "/api/v1/watchlist/items/{id_externo}", "quitarlo de favoritos"),
    # ── Webhooks: la integración que no hace polling ────────────────────────
    _P("GET", "/api/v1/webhooks", "listar las suscripciones"),
    _P("POST", "/api/v1/webhooks", "crear una suscripción"),
    _P("GET", "/api/v1/webhooks/event-types", "qué eventos existen, sin leer la documentación"),
    _P("GET", "/api/v1/webhooks/{webhook_id}", "leer una suscripción"),
    _P("PATCH", "/api/v1/webhooks/{webhook_id}", "cambiar URL, eventos o estado"),
    _P("DELETE", "/api/v1/webhooks/{webhook_id}", "dar de baja la suscripción"),
    _P(
        "GET",
        "/api/v1/webhooks/{webhook_id}/deliveries",
        "diagnosticar entregas sin abrir un ticket",
    ),
    _P("POST", "/api/v1/webhooks/{webhook_id}/ping", "probar el receptor al configurarlo"),
    _P("POST", "/api/v1/webhooks/{webhook_id}/rotate-secret", "rotar el secreto de firma"),
    # ── Cuenta y credenciales ───────────────────────────────────────────────
    _P("GET", "/api/v1/me/keys", "ver las claves de API propias"),
    _P("POST", "/api/v1/me/keys", "crear una clave de API nueva"),
    _P("POST", "/api/v1/me/keys/rotate", "rotarla sin perder el acceso"),
    _P("GET", "/api/v1/me/data", "portabilidad RGPD: es un derecho, no una función"),
    # ── Salud ───────────────────────────────────────────────────────────────
    _P("GET", "/api/v1/health", "lo que un cliente sondea antes de culpar a su código"),
)


def claves_publicas() -> frozenset[tuple[str, str]]:
    """``{(metodo_en_minúsculas, ruta)}`` del contrato."""
    return frozenset(op.clave for op in SUPERFICIE_PUBLICA)


def marcar_publicas(schema: dict[str, Any]) -> int:
    """Estampa ``x-public: true`` en las operaciones del contrato. Devuelve cuántas.

    Se hace sobre el schema ya generado y no con ``openapi_extra`` en cada ruta
    por lo que dice la cabecera del módulo. El resultado en el fichero es el
    mismo.
    """
    publicas = claves_publicas()
    marcadas = 0
    rutas = schema.get("paths")
    if not isinstance(rutas, dict):
        return 0
    for ruta, operaciones in rutas.items():
        if not isinstance(operaciones, dict):
            continue
        for metodo, operacion in operaciones.items():
            if isinstance(operacion, dict) and (metodo.lower(), ruta) in publicas:
                operacion[EXTENSION] = True
                marcadas += 1
    return marcadas


def _refs(nodo: Any) -> set[str]:
    """Nombres de ``#/components/schemas/X`` alcanzables desde ``nodo``."""
    encontrados: set[str] = set()
    if isinstance(nodo, dict):
        ref = nodo.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            encontrados.add(ref.rsplit("/", 1)[-1])
        for valor in nodo.values():
            encontrados |= _refs(valor)
    elif isinstance(nodo, list):
        for valor in nodo:
            encontrados |= _refs(valor)
    return encontrados


def filtrar_publico(schema: dict[str, Any]) -> dict[str, Any]:
    """Devuelve el spec reducido al contrato, con sus esquemas y nada más.

    La poda de ``components/schemas`` es **transitiva**: un DTO referencia a
    otros y quedarse sólo con los de primer nivel produciría un fichero con
    ``$ref`` colgando, que ningún generador de clientes acepta.
    ``tests/test_superficie_publica.py`` comprueba que no queda ninguno suelto.

    Lo que se conserva fuera de ``paths``: ``openapi``, ``info``, ``servers``,
    ``tags`` y ``components/securitySchemes`` — sin el último, el fichero no
    dice cómo autenticarse y no sirve para generar un cliente.
    """
    publicas = claves_publicas()
    rutas_origen = schema.get("paths")
    rutas: dict[str, Any] = {}
    if isinstance(rutas_origen, dict):
        for ruta, operaciones in rutas_origen.items():
            if not isinstance(operaciones, dict):
                continue
            elegidas = {
                metodo: operacion
                for metodo, operacion in operaciones.items()
                if (metodo.lower(), ruta) in publicas
            }
            if elegidas:
                rutas[ruta] = elegidas

    componentes_origen = schema.get("components")
    esquemas_origen: dict[str, Any] = {}
    if isinstance(componentes_origen, dict):
        crudos = componentes_origen.get("schemas")
        if isinstance(crudos, dict):
            esquemas_origen = crudos

    # Cierre transitivo sobre los `$ref` alcanzables desde las rutas elegidas.
    pendientes = _refs(rutas)
    alcanzados: set[str] = set()
    while pendientes:
        nombre = pendientes.pop()
        if nombre in alcanzados or nombre not in esquemas_origen:
            continue
        alcanzados.add(nombre)
        pendientes |= _refs(esquemas_origen[nombre]) - alcanzados

    componentes: dict[str, Any] = {
        "schemas": {n: esquemas_origen[n] for n in sorted(alcanzados)},
    }
    if isinstance(componentes_origen, dict) and "securitySchemes" in componentes_origen:
        componentes["securitySchemes"] = componentes_origen["securitySchemes"]

    publico: dict[str, Any] = {
        "openapi": schema.get("openapi", "3.1.0"),
        "info": dict(schema.get("info", {})),
        "paths": rutas,
        "components": componentes,
    }
    for opcional in ("servers", "security"):
        if opcional in schema:
            publico[opcional] = schema[opcional]

    # `tags`, sólo los que alguna operación pública usa: una lista de etiquetas
    # que nombran secciones invisibles confunde más que ayuda.
    etiquetas_usadas = {
        etiqueta
        for operaciones in rutas.values()
        for operacion in operaciones.values()
        if isinstance(operacion, dict)
        for etiqueta in operacion.get("tags", [])
    }
    etiquetas = schema.get("tags")
    if isinstance(etiquetas, list):
        conservadas = [
            t for t in etiquetas if isinstance(t, dict) and t.get("name") in etiquetas_usadas
        ]
        if conservadas:
            publico["tags"] = conservadas

    info = publico["info"]
    info["title"] = f"{info.get('title', 'TenderFlow API')} — superficie pública"
    info["description"] = (
        "Las operaciones con soporte y contrato de compatibilidad. El resto de "
        "la API existe y funciona, pero es interna: cambia sin aviso y no debe "
        "integrarse. La lista y el motivo de cada línea están en "
        "`api/superficie_publica.py`; quitar una operación de aquí va por RFC."
    )
    return publico
