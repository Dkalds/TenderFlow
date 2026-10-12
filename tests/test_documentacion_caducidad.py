"""Caducidad de la documentación acreditativa: el juicio puro (sin BD).

``services/documentacion_caducidad.py`` decide, para un documento declarado en
el perfil de capacidad, en qué estado está, qué umbral de aviso ha cruzado y
con qué texto se avisa. Se prueba entero sin base de datos: el mismo juicio
sirve a la pestaña Organización y al paso del cierre que avisa.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.documentacion_caducidad import (
    UMBRALES_DIAS,
    categoria_de,
    clave_documento,
    estado_de,
    texto_aviso,
    umbral_cruzado,
    vigencias,
)
from shared.dto import OrganizationCertification

HOY = date(2026, 10, 12)


def _en(dias: int) -> date:
    return HOY + timedelta(days=dias)


def test_los_umbrales_son_los_del_producto():
    """60, 30 y 7 días antes, y al caducar (0)."""
    assert UMBRALES_DIAS == (60, 30, 7, 0)


@pytest.mark.parametrize(
    ("vigente_hasta", "umbral"),
    [
        (None, None),
        (_en(61), None),
        (_en(60), 60),
        (_en(31), 60),
        (_en(30), 30),
        (_en(8), 30),
        (_en(7), 7),
        # El último día de vigencia todavía vale: no ha caducado.
        (_en(0), 7),
        (_en(-1), 0),
        (_en(-400), 0),
    ],
)
def test_umbral_cruzado_es_el_mas_cercano(vigente_hasta, umbral):
    """Solo el umbral más próximo: una pasada que llega tarde no avisa tres veces."""
    assert umbral_cruzado(vigente_hasta, HOY) == umbral


@pytest.mark.parametrize(
    ("vigente_hasta", "estado", "dias"),
    [
        (None, "sin_caducidad", None),
        (_en(61), "vigente", 61),
        (_en(60), "caduca_pronto", 60),
        (_en(0), "caduca_pronto", 0),
        (_en(-1), "caducado", -1),
    ],
)
def test_estado_y_dias_restantes(vigente_hasta, estado, dias):
    assert estado_de(vigente_hasta, HOY) == (estado, dias)


def test_categoria_tecnica_o_administrativa():
    assert categoria_de("certificacion_tecnica") == "tecnica"
    for tipo in (
        "corriente_aeat",
        "corriente_seguridad_social",
        "rolece",
        "clasificacion_empresarial",
    ):
        assert categoria_de(tipo) == "administrativa"


def test_la_clave_del_documento_no_depende_de_mayusculas_ni_espacios():
    """El PUT reemplaza el perfil entero: la fila cambia de id, el documento no."""
    a = clave_documento("certificacion_tecnica", "  ISO/IEC  27001 ")
    b = clave_documento("certificacion_tecnica", "iso/iec 27001")
    assert a == b
    assert a != clave_documento("corriente_aeat", "iso/iec 27001")


@pytest.mark.parametrize(
    ("dias", "titulo"),
    [(20, "Caduca en 20 días"), (1, "Caduca mañana"), (0, "Caduca hoy"), (-3, "Ha caducado")],
)
def test_texto_del_aviso(dias, titulo):
    encabezado, detalle = texto_aviso("Certificado AEAT", _en(dias), dias)
    assert encabezado == titulo
    assert "Certificado AEAT" in detalle
    assert _en(dias).isoformat() in detalle


def test_vigencias_ordenadas_por_la_proxima_caducidad():
    """Lo caducado primero (lo más urgente), después por fecha, y lo que no
    declara caducidad al final: no tiene fecha con la que competir."""
    declarados = [
        OrganizationCertification(nombre="ISO 9001", vigente_hasta=_en(200)),
        OrganizationCertification(nombre="ROLECE", tipo="rolece", vigente_hasta=None),
        OrganizationCertification(nombre="AEAT", tipo="corriente_aeat", vigente_hasta=_en(20)),
        OrganizationCertification(
            nombre="Seguridad Social", tipo="corriente_seguridad_social", vigente_hasta=_en(-2)
        ),
    ]

    filas = vigencias(declarados, HOY)

    assert [f.nombre for f in filas] == ["Seguridad Social", "AEAT", "ISO 9001", "ROLECE"]
    assert [f.estado for f in filas] == ["caducado", "caduca_pronto", "vigente", "sin_caducidad"]
    assert [f.dias_restantes for f in filas] == [-2, 20, 200, None]
    assert [f.categoria for f in filas] == [
        "administrativa",
        "administrativa",
        "tecnica",
        "administrativa",
    ]


def test_un_documento_administrativo_no_se_acredita_por_una_persona():
    """La AEAT certifica a la empresa: declararla como título del equipo es un error."""
    with pytest.raises(ValueError, match="empresa"):
        OrganizationCertification(nombre="AEAT", tipo="corriente_aeat", ambito="team")


def test_lo_guardado_antes_de_v147_es_certificacion_tecnica():
    """Retrocompatible: una fila sin tipo valida y se lee como certificación técnica."""
    antigua = OrganizationCertification.model_validate({"nombre": "ENS", "ambito": "company"})
    assert antigua.tipo == "certificacion_tecnica"


# ── Paso del cierre (ADR-012) ───────────────────────────────────────────────


def test_el_paso_diario_va_antes_del_reparto_y_es_advisory():
    """Antes de `event_dispatch` para que el aviso salga en la misma pasada.

    Advisory: los avisos tienen semanas de margen y la ventana es diaria; un
    fallo lo recupera la pasada siguiente y no puede tumbar la ingesta.
    """
    from scheduler.pipeline_runs import CANONICAL_STEPS, STEP_DEPS, step_tier

    assert CANONICAL_STEPS.index("documentacion_avisos") < CANONICAL_STEPS.index("event_dispatch")
    assert step_tier("documentacion_avisos") == "advisory"
    assert "documentacion_avisos" not in STEP_DEPS


def test_el_paso_corre_una_vez_al_dia(monkeypatch):
    """Cadencia propia: la pasada corre cada cuatro horas, el aviso es diario."""
    import scheduler.pipeline_runs as pipeline
    from services import documentacion_caducidad

    ventanas: list[tuple[str, int]] = []
    llamadas: list[str] = []

    def _periodico(nombre, ttl, fn):
        ventanas.append((nombre, ttl))
        fn()
        return "ok"

    monkeypatch.setattr(pipeline, "_run_periodic", _periodico)
    monkeypatch.setattr(
        documentacion_caducidad,
        "emitir_avisos_de_caducidad",
        lambda: llamadas.append("emitir") or 3,
    )

    assert pipeline._run_documentacion_avisos() == "ok"
    assert ventanas == [("documentacion_avisos", 24 * 60 * 60)]
    assert llamadas == ["emitir"]
