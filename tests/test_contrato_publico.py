"""La superficie pública de la API es un contrato, y como tal se fija aquí.

Qué protege cada test
---------------------
1. **Que lo declarado existe.** Una operación en la lista que ya no está en la
   app significa que el spec público publica una ruta muerta: el integrador
   escribe el cliente y recibe un 404. Como la lista vive lejos del código
   (a propósito, ver `api/contrato_publico.py`), esta comprobación es lo que
   impide que se desincronice.
2. **Que el spec público es usable.** Sin el cierre transitivo de `$ref`, el
   fichero sale con referencias colgando y ningún generador de clientes lo
   acepta — un fallo que sólo se ve al intentar usarlo, o sea, en casa del
   cliente.
3. **Que nada interno se cuela.** Administración, banderas, `/pursuits` o
   `/analytics` en el fichero público serían promesas que nadie quiso hacer.
4. **Ratchet: el contrato no encoge en silencio.** Añadir es barato; quitar
   rompe a quien la use y va por RFC. El pinchado obliga a que sacar una línea
   sea un cambio visible en el diff de este fichero.
"""

from __future__ import annotations

from typing import Any

import pytest

from api.contrato_publico import (
    CONTRATO_PUBLICO,
    EXTENSION,
    claves_publicas,
    filtrar_publico,
    marcar_publicas,
)

#: Prefijos que **nunca** pueden aparecer en el spec público, con su motivo.
#: No sustituyen a la lista blanca: son la red por si alguien añade a la lista
#: algo de estos árboles sin pensarlo.
_PROHIBIDOS: dict[str, str] = {
    "/api/v1/admin/": "administración interna",
    "/api/v1/feature-flags": "banderas de funcionalidad: estado interno del despliegue",
    "/api/v1/analytics/": "agregados cuya forma sigue al modelo de datos",
    "/api/v1/pursuits": "la vertical de la consola; su contrato es la pantalla",
    "/api/v1/models/": "registro de modelos ML",
    "/api/v1/auth/": "flujo de sesión de navegador, no de integración",
    "/api/v1/publico/": "superficie del sitio web (SEO), no la API que se integra",
    "/api/v1/security/": "diagnóstico interno",
}

#: **Ratchet.** El contrato vigente, una línea por operación. Añadir aquí es
#: una decisión de producto; quitar es romper a alguien y va por RFC con fecha.
_CONTRATO_PINCHADO: frozenset[tuple[str, str]] = frozenset(
    {
        ("get", "/api/v1/adjudicaciones"),
        ("delete", "/api/v1/follows/{target_type}/{target_id}"),
        ("get", "/api/v1/follows"),
        ("post", "/api/v1/follows"),
        ("get", "/api/v1/empresas"),
        ("get", "/api/v1/empresas/{empresa_id}"),
        ("get", "/api/v1/exports/calendario.ics"),
        ("get", "/api/v1/exports/download"),
        ("get", "/api/v1/health"),
        ("get", "/api/v1/licitaciones"),
        ("get", "/api/v1/licitaciones/cursor"),
        ("get", "/api/v1/licitaciones/{id_externo}"),
        ("get", "/api/v1/licitaciones/{id_externo}/documentos"),
        ("post", "/api/v1/licitaciones/bulk-get"),
        ("post", "/api/v1/licitaciones/search"),
        ("get", "/api/v1/me/data"),
        ("get", "/api/v1/me/keys"),
        ("post", "/api/v1/me/keys"),
        ("post", "/api/v1/me/keys/rotate"),
        ("get", "/api/v1/meta/filters"),
        ("get", "/api/v1/meta/last-extraction"),
        ("get", "/api/v1/resoluciones"),
        ("delete", "/api/v1/watchlist/items/{id_externo}"),
        ("get", "/api/v1/watchlist/items"),
        ("post", "/api/v1/watchlist/items"),
        ("get", "/api/v1/webhooks"),
        ("post", "/api/v1/webhooks"),
        ("get", "/api/v1/webhooks/event-types"),
        ("delete", "/api/v1/webhooks/{webhook_id}"),
        ("get", "/api/v1/webhooks/{webhook_id}"),
        ("patch", "/api/v1/webhooks/{webhook_id}"),
        ("get", "/api/v1/webhooks/{webhook_id}/deliveries"),
        ("post", "/api/v1/webhooks/{webhook_id}/ping"),
        ("post", "/api/v1/webhooks/{webhook_id}/rotate-secret"),
    }
)


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    from api.app import app

    return dict(app.openapi())


# ── 1. Lo declarado existe ──────────────────────────────────────────────────


def test_toda_operacion_declarada_existe_en_la_app(schema: dict[str, Any]) -> None:
    reales = {
        (metodo.lower(), ruta)
        for ruta, operaciones in schema["paths"].items()
        for metodo in operaciones
        if metodo.lower() in {"get", "post", "put", "patch", "delete"}
    }
    fantasmas = sorted(claves_publicas() - reales)
    assert not fantasmas, (
        "Operación(es) declaradas públicas que la app ya no expone. El spec "
        "público las publicaría y el cliente que las use recibiría un 404. "
        f"Corregí `api/contrato_publico.py`: {fantasmas}"
    )


def test_cada_operacion_declara_su_motivo() -> None:
    """Una línea sin motivo es una línea que nadie podrá revisar."""
    sin_motivo = [f"{op.metodo} {op.ruta}" for op in CONTRATO_PUBLICO if len(op.porque) < 15]
    assert not sin_motivo, sin_motivo


def test_no_hay_duplicados() -> None:
    assert len(claves_publicas()) == len(CONTRATO_PUBLICO)


# ── 2. El spec público es usable ────────────────────────────────────────────


def test_el_spec_publico_no_deja_referencias_colgando(schema: dict[str, Any]) -> None:
    """El fallo que sólo se ve al generar el cliente, o sea, en casa del cliente."""
    from api.contrato_publico import _refs

    publico = filtrar_publico(schema)
    disponibles = set(publico["components"]["schemas"])
    referidos = _refs(publico["paths"]) | _refs(publico["components"]["schemas"])
    colgando = sorted(referidos - disponibles)
    assert not colgando, (
        "El spec público referencia esquemas que no incluye: la poda de "
        f"`components` tiene que ser transitiva. Faltan: {colgando}"
    )


def test_el_spec_publico_conserva_como_autenticarse(schema: dict[str, Any]) -> None:
    """Sin `securitySchemes` el fichero no dice cómo autenticarse y no sirve."""
    publico = filtrar_publico(schema)
    assert publico["components"].get("securitySchemes")


def test_el_spec_publico_pesa_bastante_menos(schema: dict[str, Any]) -> None:
    """Si el filtrado no reduce, es que no está filtrando."""
    publico = filtrar_publico(schema)
    assert len(publico["paths"]) < len(schema["paths"]) / 2
    assert len(publico["components"]["schemas"]) < len(schema["components"]["schemas"])


# ── 3. Nada interno se cuela ────────────────────────────────────────────────


def test_el_spec_publico_no_contiene_superficie_interna(schema: dict[str, Any]) -> None:
    publico = filtrar_publico(schema)
    colados = [
        f"{ruta} ({motivo})"
        for ruta in publico["paths"]
        for prefijo, motivo in _PROHIBIDOS.items()
        if ruta.startswith(prefijo)
    ]
    assert not colados, (
        f"Superficie interna en el spec público: {colados}. Publicarla la "
        "convierte en una promesa que nadie decidió hacer."
    )


def test_la_marca_x_public_llega_al_spec_completo(schema: dict[str, Any]) -> None:
    """La marca viaja en el artefacto que ya existía, no sólo en el filtrado."""
    copia = dict(schema)
    marcadas = marcar_publicas(copia)
    assert marcadas == len(CONTRATO_PUBLICO)

    con_marca = {
        (metodo.lower(), ruta)
        for ruta, operaciones in copia["paths"].items()
        for metodo, operacion in operaciones.items()
        if isinstance(operacion, dict) and operacion.get(EXTENSION) is True
    }
    assert con_marca == claves_publicas()


# ── 4. Ratchet ──────────────────────────────────────────────────────────────


def test_el_contrato_publico_es_el_pinchado() -> None:
    """Cambiar la superficie pública tiene que verse en el diff de este fichero.

    Las dos direcciones importan, y por motivos distintos:

    * **Lo que sobra** (está en el código y no aquí) es una operación que se
      publicó sin que nadie decidiera publicarla. Se arregla añadiéndola aquí
      —después de decidirlo—.
    * **Lo que falta** (está aquí y no en el código) es una retirada. Eso rompe
      a quien la use y no se cierra actualizando el test: va por RFC con fecha,
      como la retirada de los exports asíncronos.
    """
    vigente = claves_publicas()

    sobran = sorted(vigente - _CONTRATO_PINCHADO)
    assert not sobran, (
        "Operación(es) nuevas en la superficie pública sin pinchar aquí. Si "
        f"la decisión es publicarlas, añadilas a `_CONTRATO_PINCHADO`: {sobran}"
    )

    faltan = sorted(_CONTRATO_PINCHADO - vigente)
    assert not faltan, (
        "Operación(es) RETIRADAS del contrato público. Eso rompe a quien las "
        "use: no se arregla borrando la línea de este test, se arregla con un "
        f"RFC con fecha de retirada (docs/rfc/). Retiradas: {faltan}"
    )
