"""Catálogo de eventos de dominio: vocabulario cerrado y suscripciones (S4.1/S4.2).

El catálogo existe para que un evento con el nombre mal escrito no se pierda en
silencio en una tabla append-only. Estos tests son ese contrato: qué se acepta,
qué se rechaza y qué cubre cada comodín de suscripción.

Sin BD: ``shared/events.py`` es puro a propósito (lo importan la API y el
scheduler), así que su contrato se comprueba sin Postgres.
"""

from __future__ import annotations

import pytest

from shared.events import (
    CANALES,
    CATALOGO,
    FAMILIAS,
    FORMATOS,
    TIPOS,
    PayloadIncompleto,
    TipoDeEventoDesconocido,
    especificacion,
    suscripcion_cubre,
    suscripciones_validas,
    tipos_de_canal,
    validar_payload,
    validar_tipo,
)


def test_catalogo_rechaza_un_tipo_fuera_de_el():
    """Criterio de aceptación de S4.1: un tipo que no está, no pasa."""
    with pytest.raises(TipoDeEventoDesconocido):
        validar_tipo("pursuit.inventado")


def test_catalogo_rechaza_una_familia_entera_inventada():
    with pytest.raises(TipoDeEventoDesconocido):
        validar_tipo("factura.emitida")


def test_catalogo_acepta_los_tipos_declarados():
    for tipo in TIPOS:
        assert validar_tipo(tipo) == tipo


def test_payload_incompleto_falla_en_el_productor():
    """El contrato mínimo del payload se comprueba al escribir, no al entregar."""
    with pytest.raises(PayloadIncompleto):
        validar_payload("pursuit.created", {"pursuit_id": 1})


def test_payload_completo_pasa():
    validar_payload(
        "pursuit.created",
        {"pursuit_id": 1, "licitacion_id": "LIC-1", "organization_id": 7},
    )


def test_toda_especificacion_declara_canales_conocidos():
    for tipo in TIPOS:
        spec = especificacion(tipo)
        assert spec.canales, f"{tipo} no sale por ningún canal"
        for canal in spec.canales:
            assert canal in CANALES


def test_los_eventos_in_app_declaran_su_tipo_de_notificacion():
    """Sin ``tipo_notificacion`` la alerta no tendría clave de deduplicación."""
    for tipo in tipos_de_canal("in_app"):
        assert especificacion(tipo).tipo_notificacion, tipo


def test_la_preferencia_de_correo_solo_la_tienen_los_eventos_personales():
    """Un evento sin destinatario humano no puede tener preferencia de correo."""
    for tipo in TIPOS:
        spec = especificacion(tipo)
        if spec.preferencia_email:
            assert "digest" in spec.canales, tipo


def test_toda_familia_del_catalogo_esta_declarada():
    """``FAMILIAS`` gobierna los comodines: una familia sin declarar no se puede
    suscribir con ``x.*`` aunque sus tipos existan."""
    for tipo in TIPOS:
        assert tipo.split(".", 1)[0] in FAMILIAS, tipo


def test_suscripciones_validas_incluye_comodines_y_tipos():
    validas = set(suscripciones_validas())
    assert "*" in validas
    assert "pursuit.*" in validas
    assert "licitacion.*" in validas
    assert TIPOS.issubset(validas)


@pytest.mark.parametrize(
    ("suscripciones", "tipo", "esperado"),
    [
        ({"*"}, "pursuit.created", True),
        ({"pursuit.*"}, "pursuit.created", True),
        ({"pursuit.*"}, "licitacion.cambiada", False),
        ({"pursuit.created"}, "pursuit.created", True),
        ({"pursuit.created"}, "pursuit.assigned", False),
        (set(), "pursuit.created", False),
    ],
)
def test_suscripcion_cubre(suscripciones, tipo, esperado):
    assert suscripcion_cubre(suscripciones, tipo) is esperado


def test_los_tres_formatos_del_catalogo_son_los_de_d13():
    assert set(FORMATOS) == {"json", "slack_blocks", "teams_adaptive_card"}


def test_el_catalogo_cubre_los_hechos_que_el_plan_enumera():
    """S4.1 enumera qué mutaciones escriben evento. Si alguna sale del catálogo,
    su productor deja de compilar y este test dice cuál falta."""
    esperados = {
        "pursuit.created",
        "pursuit.state_changed",
        "pursuit.decided",
        "pursuit.assigned",
        "pursuit.commented",
        "watchlist_rule.matched",
        "adjudicacion.detectada",
        "renovacion.en_ventana",
        "ficha.extraida",
        "licitacion.cambiada",
    }
    assert esperados.issubset(set(CATALOGO))
