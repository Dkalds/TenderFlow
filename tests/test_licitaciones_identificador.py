"""Un expediente se direcciona de una sola forma: ``{id_externo:path}``.

El problema que cierra
----------------------
Un ``id_externo`` de PLACSP lleva **barras y espacios** —el ejemplo que el
propio repositorio usa en sus tests es ``"PA-S 2026/000058"``—. Una barra no
cabe en un segmento de ruta: el servidor ASGI decodifica ``%2F`` a ``/``
*antes* del routing, así que el conversor por defecto de Starlette (``[^/]+``)
no llega a ver el identificador completo.

Hasta esta tanda el árbol tenía **tres** formas de nombrar lo mismo:

- ``{id_externo:path}`` en la mayoría de los hijos (correcto);
- ``{id_externo}`` —segmento simple— en el detalle, en ``/similares`` y en la
  página de un documento, que por tanto daban 404 con esos ids;
- ``{licitacion_id:path}`` en ``/eventos``, ``/prediccion-baja`` y
  ``/escenarios-precio``, que funcionaban pero llamaban al mismo dato de otra
  manera, así que el esquema publicaba dos nombres para un solo concepto.

El detalle se tapaba con un ``app.add_api_route(..., include_in_schema=False)``
al final de ``api/app.py``: resolvía el 404 en runtime, pero dejaba el esquema
publicando la variante rota —la que usa quien genera un cliente— y hacía
depender la corrección de un orden de registro que no comprobaba nadie.

Estos tests son ese comprobador. Los dos primeros son estructurales y fallan
ante cualquier ruta nueva que se salga de la convención; los demás recorren el
camino real con un id con barra y con espacio.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

#: Id con barra **y** espacio, como los reales de PLACSP.
ID_CON_BARRA = "PA-S 2026/000058"

_PREFIJO = "/api/v1/licitaciones"


def _rutas_de_licitaciones() -> list[Any]:
    """Rutas de la aplicación bajo ``/api/v1/licitaciones``, en orden de registro."""
    from api.app import app

    return [r for r in app.routes if str(getattr(r, "path", "")).startswith(_PREFIJO)]


def test_toda_ruta_de_expediente_usa_el_mismo_parametro() -> None:
    """Ni ``{id_externo}`` a secas ni ``{licitacion_id}``: uno y con ``:path``."""
    desviadas = []
    for ruta in _rutas_de_licitaciones():
        path = str(ruta.path)
        # Sólo las que direccionan un expediente concreto; `/licitaciones`,
        # `/cursor`, `/search`, `/comparar` y `/bulk-get` no llevan parámetro.
        if not path.startswith(f"{_PREFIJO}/{{"):
            continue
        if not path.startswith(f"{_PREFIJO}/{{id_externo:path}}"):
            desviadas.append(f"{sorted(getattr(ruta, 'methods', []))} {path}")

    assert not desviadas, (
        "Estas rutas nombran el expediente de otra forma. Un id_externo real "
        f"({ID_CON_BARRA!r}) lleva barras, así que el parámetro tiene que ser "
        "{id_externo:path} en todas: " + "; ".join(desviadas)
    )


def test_el_detalle_glotón_se_registra_el_ultimo() -> None:
    """El catch-all no puede ensombrecer a sus hermanos.

    ``/licitaciones/{id_externo:path}`` casa también con
    ``/licitaciones/X/eventos``. Starlette se queda con la **primera** ruta que
    case, así que el detalle tiene que ir detrás de todos los hijos —incluidos
    los que viven en ``api/routes/eventos.py``, ``predicciones.py`` y
    ``ask.py``, que se incluyen en otro momento—. Por eso su router va aparte y
    ``api/app.py`` lo incluye el último.
    """
    rutas = _rutas_de_licitaciones()
    detalle = f"{_PREFIJO}/{{id_externo:path}}"
    posiciones = [i for i, r in enumerate(rutas) if str(r.path) == detalle]
    assert posiciones, "No existe la ruta de detalle con el conversor :path"
    assert posiciones[-1] == len(rutas) - 1, (
        "La ruta de detalle ya no es la última bajo /api/v1/licitaciones. "
        "Algo se registró después y queda inalcanzable: "
        f"{[str(r.path) for r in rutas[posiciones[-1] + 1 :]]}"
    )


def test_el_esquema_publica_el_detalle() -> None:
    """Y no como una operación oculta.

    El fallback anterior era ``include_in_schema=False``: quien generaba un
    cliente desde el spec no veía esta operación con su forma real.
    """
    from api.app import app

    esquema = app.openapi()
    assert "/api/v1/licitaciones/{id_externo}" in esquema["paths"]
    assert "get" in esquema["paths"]["/api/v1/licitaciones/{id_externo}"]


def test_el_esquema_no_deja_rastro_del_nombre_viejo() -> None:
    from api.app import app

    con_nombre_viejo = [p for p in app.openapi()["paths"] if "{licitacion_id}" in p]
    assert not con_nombre_viejo, "El esquema todavía publica {licitacion_id} en " + ", ".join(
        con_nombre_viejo
    )


# ── El paquete por familias ─────────────────────────────────────────────────


def test_ninguna_familia_se_queda_sin_incluir() -> None:
    """Un módulo de familia con router y sin ``include_router`` es invisible.

    Es el modo de fallo propio de partir un router en paquete: el módulo
    importa, pasa mypy, pasa ruff, y sus endpoints sencillamente no existen. No
    lo detecta ningún test de esos endpoints —no hay a qué llamarlos— salvo que
    alguien los cubriera uno a uno. Esto lo detecta en un sitio.
    """
    import importlib
    import pkgutil

    import api.routes.licitaciones as paquete

    registradas = {str(r.path) for r in paquete.router.routes}
    registradas |= {str(r.path) for r in paquete.router_detalle.routes}

    huerfanas: list[str] = []
    for info in pkgutil.iter_modules(paquete.__path__):
        if info.name.startswith("_") or info.name == "modelos":
            continue
        modulo = importlib.import_module(f"{paquete.__name__}.{info.name}")
        propio = getattr(modulo, "router", None)
        if propio is None:
            continue
        for ruta in propio.routes:
            if str(ruta.path) not in registradas:
                huerfanas.append(f"{info.name}: {ruta.path}")

    assert not huerfanas, (
        "Estas rutas existen en su familia pero el paquete no las incluye, así "
        "que no responden: " + "; ".join(huerfanas)
    )


def test_el_paquete_sigue_sirviendo_los_nombres_que_el_arbol_importa() -> None:
    """Partir el módulo no puede obligar a tocar a quien lo importaba.

    Hay tests y scripts que hacen ``from api.routes.licitaciones import
    LicitacionSummary`` (y ``SimilaresResult``, ``_get_classifier``,
    ``SUNSET_LISTADO_POR_OFFSET``…). Una reorganización interna no es motivo
    para cambiarles el import.
    """
    import api.routes.licitaciones as paquete

    for nombre in (
        "AdjudicacionSummary",
        "LicitacionDetail",
        "LicitacionSummary",
        "LoteOut",
        "SUNSET_LISTADO_POR_OFFSET",
        "SimilarOut",
        "SimilaresResult",
        "_get_classifier",
        "get_licitacion",
        "router",
        "router_detalle",
    ):
        assert hasattr(paquete, nombre), f"El paquete dejó de exportar {nombre}"


# ── Camino real con un id con barra ─────────────────────────────────────────


def _ctx(user_id: int, email: str) -> dict[str, Any]:
    from shared.identity import user_key_from_email

    return {
        "user_id": user_id,
        "email": email,
        "display_name": "Test User",
        "is_admin": False,
        "auth_method": "session",
        "authenticated_at": datetime.now(UTC).isoformat(),
        "user_key": user_key_from_email(email, user_id),
    }


@pytest.fixture
def cliente_autenticado(client, api_db):
    """`client` con `require_any_auth` sustituido y un expediente sembrado."""
    from api.app import app
    from api.routes.dual_auth import require_any_auth
    from db.upsert import Licitacion, upsert_licitaciones
    from db.users import create_user

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=ID_CON_BARRA,
                titulo="Expediente con barra en el identificador",
                organo_contratacion="Ministerio de Prueba",
                cpv="72267100-0",
                estado="PUB",
            )
        ]
    )
    user_id = create_user(
        email="identificador@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
    )
    app.dependency_overrides[require_any_auth] = lambda: _ctx(
        int(user_id), "identificador@example.test"
    )
    try:
        yield client
    finally:
        # `pop`, no `clear`: el diccionario es global y lo comparten los otros
        # ficheros de tests. Vaciarlo entero convierte a este módulo en fuente
        # de contaminación cruzada.
        app.dependency_overrides.pop(require_any_auth, None)


def test_el_detalle_resuelve_un_id_con_barra_y_espacio(cliente_autenticado) -> None:
    with cliente_autenticado as c:
        resp = c.get(f"/api/v1/licitaciones/{ID_CON_BARRA}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id_externo"] == ID_CON_BARRA


def test_similares_resuelve_un_id_con_barra(cliente_autenticado) -> None:
    """Era 404 hasta esta tanda: `/similares` usaba el conversor por defecto."""
    with cliente_autenticado as c:
        resp = c.get(f"/api/v1/licitaciones/{ID_CON_BARRA}/similares")
    assert resp.status_code == 200, resp.text
    assert resp.json()["licitacion_id"] == ID_CON_BARRA


def test_documentos_resuelve_un_id_con_barra(cliente_autenticado) -> None:
    with cliente_autenticado as c:
        resp = c.get(f"/api/v1/licitaciones/{ID_CON_BARRA}/documentos")
    assert resp.status_code == 200, resp.text


def test_el_detalle_no_se_come_a_sus_hermanos(cliente_autenticado) -> None:
    """La otra mitad del riesgo: que el catch-all engulla las sub-rutas.

    Si el detalle ganara, estas respuestas serían el cuerpo del detalle (o su
    404) en vez del recurso pedido. Se comprueba con la forma de la respuesta,
    no con el código: 200 y 404 los puede dar cualquiera de los dos.
    """
    with cliente_autenticado as c:
        eventos = c.get(f"/api/v1/licitaciones/{ID_CON_BARRA}/eventos")
        tecnologias = c.get(f"/api/v1/licitaciones/{ID_CON_BARRA}/tecnologias")

    # `titulo` lo trae siempre el detalle y ninguno de estos dos; `items`, al
    # revés. Se mira la forma y no el código porque 200 y 404 los puede dar
    # cualquiera de los dos handlers.
    for nombre, resp in (("eventos", eventos), ("tecnologias", tecnologias)):
        assert resp.status_code == 200, f"{nombre}: {resp.text}"
        cuerpo = resp.json()
        assert "items" in cuerpo, f"{nombre} no devolvió su propia forma: {cuerpo}"
        assert "titulo" not in cuerpo, f"el detalle se comió {nombre}: {cuerpo}"
