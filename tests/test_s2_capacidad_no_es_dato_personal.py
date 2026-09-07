"""S2.2 — el perfil de capacidad es dato corporativo, no personal.

RGPD Art. 17/20 cubren los datos **personales** de quien los pide. Las
certificaciones, la facturación, las referencias y los perfiles de equipo
pertenecen a la organización: exportarlos con la cuenta de un empleado sería
entregarle información de su empresa, y borrarlos al borrar su cuenta dejaría
al resto del equipo sin el dato con el que se contrastan los pliegos.

El test se escribe contra el **código** de ``services/gdpr.py`` y no contra una
BD sembrada a propósito: lo que hay que impedir es que alguien añada mañana la
línea que exporta o borra estas tablas, y eso se ve leyendo qué toca el módulo.
"""

from __future__ import annotations

import inspect

import services.gdpr as gdpr

#: Tablas del perfil de capacidad (v112) y de la identidad fiscal (v111).
_TABLAS_CORPORATIVAS = (
    "organization_capabilities",
    "organization_certifications",
    "organization_revenues",
    "organization_references",
    "organization_team_profiles",
    "organization_nifs",
)


def test_el_servicio_gdpr_no_alcanza_las_tablas_de_capacidad() -> None:
    fuente = inspect.getsource(gdpr)
    for tabla in _TABLAS_CORPORATIVAS:
        assert tabla not in fuente, (
            f"{tabla} es dato corporativo: ni se exporta ni se borra con una cuenta."
        )


def test_el_export_de_colaboracion_no_declara_capacidad() -> None:
    """``export_collaboration_data`` enumera sus claves; ninguna es del perfil."""
    fuente = inspect.getsource(gdpr.export_collaboration_data)
    assert "capabilit" not in fuente.lower()
    assert "certificacion" not in fuente.lower()
    assert "nif" not in fuente.lower()


def test_la_anonimizacion_no_toca_el_perfil_de_la_organizacion() -> None:
    """Borrar una cuenta quita su membresía, no la capacidad de la empresa."""
    fuente = inspect.getsource(gdpr.anonymize_user_data)
    assert "capabilit" not in fuente.lower()
    assert "nif" not in fuente.lower()
    # Lo que sí debe seguir haciendo, para que este test no pase por vacío.
    assert "remove_memberships_for_user" in fuente


def test_ningun_repositorio_de_capacidad_esta_importado_en_gdpr() -> None:
    fuente = inspect.getsource(gdpr)
    assert "organization_capabilities" not in fuente
    assert "organization_nifs" not in fuente
